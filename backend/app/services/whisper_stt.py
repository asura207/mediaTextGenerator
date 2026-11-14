import os
import re
import sys
import inspect
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

# Ensure Windows discovers CUDA & cuBLAS/cuDNN DLLs installed via pip
def _setup_cuda_dlls():
    try:
        base_venv = Path(sys.executable).parent.parent
        nvidia_dir = base_venv / "Lib" / "site-packages" / "nvidia"
        if nvidia_dir.exists():
            for sub in ["cublas", "cudnn", "cuda_nvrtc"]:
                bin_dir = nvidia_dir / sub / "bin"
                if bin_dir.exists():
                    os.add_dll_directory(str(bin_dir))
                    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]
    except Exception:
        pass

_setup_cuda_dlls()

from faster_whisper import WhisperModel
from app.config import get_whisper_config
from app.services.srt_generator import optimize_subtitle_timing, format_timestamp

logger = logging.getLogger(__name__)

# Singleton Whisper model instance to avoid reloading overhead unless settings change
_whisper_model: Optional[WhisperModel] = None
_loaded_whisper_sig = None

# Known Whisper silence/BGM watermark hallucinations
_HALLUCINATION_PATTERNS = re.compile(
    r"^(?:시청해\s*주셔서\s*감사합니다|구독과\s*좋아요\s*부탁드립니다|MBC\s*뉴스.*|SBS\s*뉴스.*|KBS\s*뉴스.*|"
    r"자막\s*제공.*|한글\s*자막.*|Subtitles\s+by.*|Amara\.org.*|Thank\s+you\s+for\s+watching.*|"
    r"ご視聴ありがとうございました.*|チャンネル登録.*)$",
    re.IGNORECASE,
)


def get_whisper_model(force_cpu: bool = False) -> WhisperModel:
    global _whisper_model, _loaded_whisper_sig
    cfg = get_whisper_config()
    model_size = cfg["model_size"]
    device = "cpu" if force_cpu else cfg["device"]
    compute_type = "int8" if force_cpu else cfg["compute_type"]
    current_sig = (model_size, device, compute_type)

    if _whisper_model is None or _loaded_whisper_sig != current_sig:
        if _whisper_model is not None:
            unload_whisper_model()
        try:
            logger.info(f"Loading faster-whisper ({device}): model={model_size}, compute_type={compute_type}")
            kwargs: Dict[str, Any] = {
                "model_size_or_path": model_size,
                "device": device,
                "compute_type": compute_type,
            }
            if device == "cpu":
                kwargs["cpu_threads"] = 4
                kwargs["num_workers"] = 1
            _whisper_model = WhisperModel(**kwargs)
            _loaded_whisper_sig = current_sig
            logger.info(f"Whisper model '{model_size}' successfully loaded on {device} ({compute_type}).")
        except Exception as e:
            logger.warning(f"Failed to load Whisper '{model_size}' on {device} ({e}). Falling back to CPU (int8)...")
            _whisper_model = WhisperModel(
                model_size_or_path=model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=4,
                num_workers=1
            )
            _loaded_whisper_sig = (model_size, "cpu", "int8")
    return _whisper_model


def unload_whisper_model():
    """Frees CUDA VRAM occupied by faster-whisper before Ollama LLM refinement begins."""
    global _whisper_model, _loaded_whisper_sig
    if _whisper_model is not None:
        try:
            del _whisper_model
        except Exception:
            pass
        _whisper_model = None
        _loaded_whisper_sig = None
        import gc
        gc.collect()
        logger.info("Unloaded Whisper model from GPU VRAM to maximize free memory for LLM refinement.")


def _collapse_intra_segment_repetition(text: str) -> str:
    """Collapses infinite phrase/token repetition hallucinations inside a single segment."""
    t = text.strip()
    if not t:
        return ""
    # Collapse 4+ consecutive identical phrases/words (e.g., "네 네 네 네 네" or "ありがとう ありがとう ありがとう ありがとう")
    t = re.sub(r"\b(\S+(?:\s+\S+){0,3})(?:\s+\1){3,}\b", r"\1 \1", t)
    # Collapse 4+ contiguous repeated substrings of length >= 2 without spaces (e.g., CJK loops)
    t = re.sub(r"(.{2,12}?)\1{3,}", r"\1\1", t)
    return t.strip()


def _deduplicate_hallucinations(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filters out BGM/silence watermark hallucinations and collapses repetitive consecutive hallucination loops.
    Preserves genuine short emotional cries/screams while preventing >2 identical consecutive BGM loops.
    """
    filtered: List[Dict[str, Any]] = []
    consecutive_same_count = 0
    last_norm_text = None

    for seg in segments:
        raw_t = _collapse_intra_segment_repetition(seg.get("raw_text") or "")
        if not raw_t:
            continue
        if _HALLUCINATION_PATTERNS.match(raw_t):
            logger.debug(f"Filtered out known Whisper hallucination watermark: {raw_t}")
            continue

        norm_t = re.sub(r"[\s\.,!?\-~〜ー…]+", "", raw_t).lower()
        if norm_t and norm_t == last_norm_text:
            consecutive_same_count += 1
            # If the exact same phrase repeats more than twice in a row, skip redundant hallucination loops
            if consecutive_same_count >= 2:
                continue
        else:
            consecutive_same_count = 0
            last_norm_text = norm_t

        seg_copy = dict(seg)
        seg_copy["raw_text"] = raw_t
        seg_copy["refined_text"] = raw_t
        filtered.append(seg_copy)

    return filtered


def _run_transcribe_pass(
    model: WhisperModel,
    audio_path: Path,
    progress_callback: Optional[Callable[[float, float], None]] = None
) -> List[Dict[str, Any]]:
    """Executes faster-whisper transcription and word-gap splitting on the given model instance."""
    transcribe_kwargs: Dict[str, Any] = dict(
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(
            threshold=0.25,               # Sensitive to quiet speech while preventing BGM noise triggers
            min_silence_duration_ms=800,  # Prevents cutting mid-breath while splitting genuine pauses
            speech_pad_ms=500             # Protects initial gasps and trailing exhalations
        ),
        no_speech_threshold=0.75,
        compression_ratio_threshold=2.4,
        condition_on_previous_text=False, # Prevents silence/BGM hallucination cascading across segments
        initial_prompt="ああ、あっ、うっ、んっ、きゃあ、はぁ、いや、痛い、すごい、やめて、だめ… 아, 앗, 으윽, 꺄악, 하아, 싫어, 아파, 흑... Oh, Ah, Ugh, Wow"
    )

    # Ensure parameter compatibility across faster-whisper versions (log_prob_threshold vs logprob_threshold)
    try:
        sig_params = inspect.signature(model.transcribe).parameters
        if "log_prob_threshold" in sig_params:
            transcribe_kwargs["log_prob_threshold"] = -1.0
        elif "logprob_threshold" in sig_params:
            transcribe_kwargs["logprob_threshold"] = -1.0
        else:
            transcribe_kwargs["log_prob_threshold"] = -1.0
    except Exception:
        transcribe_kwargs["log_prob_threshold"] = -1.0

    segments_generator, info = model.transcribe(str(audio_path), **transcribe_kwargs)
    logger.info(f"Detected language '{info.language}' with probability {info.language_probability:.2f}")

    total_duration = getattr(info, "duration", None) or 1.0
    last_reported_sec = -10.0

    raw_segments: List[Dict[str, Any]] = []
    idx = 1
    for s in segments_generator:
        if progress_callback:
            curr_end = getattr(s, "end", 0.0)
            if curr_end - last_reported_sec >= 2.0 or curr_end >= total_duration - 1.0:
                last_reported_sec = curr_end
                try:
                    progress_callback(curr_end, total_duration)
                except Exception:
                    pass

        text = s.text.strip()
        if not text:
            continue

        words = getattr(s, "words", None)
        if words and len(words) > 1:
            # Check for internal silence gaps (> 1.8s) between consecutive words
            # Keep RAW word end times here (no premature +0.35s) so overlap detection in optimize_subtitle_timing is exact
            current_words = [words[0]]
            for w in words[1:]:
                gap = w.start - current_words[-1].end
                if gap > 1.8:
                    sub_text = "".join(x.word for x in current_words).strip()
                    if sub_text:
                        w_st = round(max(0.0, current_words[0].start), 3)
                        w_ed = round(max(w_st + 0.15, current_words[-1].end), 3)
                        raw_segments.append({
                            "index": idx,
                            "start": w_st,
                            "end": w_ed,
                            "start_time_str": format_timestamp(w_st),
                            "end_time_str": format_timestamp(w_ed),
                            "raw_text": sub_text,
                            "refined_text": sub_text
                        })
                        idx += 1
                    current_words = [w]
                else:
                    current_words.append(w)

            if current_words:
                sub_text = "".join(x.word for x in current_words).strip()
                if sub_text:
                    w_st = round(max(0.0, current_words[0].start), 3)
                    w_ed = round(max(w_st + 0.15, current_words[-1].end), 3)
                    raw_segments.append({
                        "index": idx,
                        "start": w_st,
                        "end": w_ed,
                        "start_time_str": format_timestamp(w_st),
                        "end_time_str": format_timestamp(w_ed),
                        "raw_text": sub_text,
                        "refined_text": sub_text
                    })
                    idx += 1
        elif words and len(words) == 1:
            w_st = round(max(0.0, words[0].start), 3)
            w_ed = round(max(w_st + 0.15, words[0].end), 3)
            raw_segments.append({
                "index": idx,
                "start": w_st,
                "end": w_ed,
                "start_time_str": format_timestamp(w_st),
                "end_time_str": format_timestamp(w_ed),
                "raw_text": text,
                "refined_text": text
            })
            idx += 1
        else:
            s_st = round(max(0.0, s.start), 3)
            s_ed = round(max(s_st + 0.15, s.end), 3)
            raw_segments.append({
                "index": idx,
                "start": s_st,
                "end": s_ed,
                "start_time_str": format_timestamp(s_st),
                "end_time_str": format_timestamp(s_ed),
                "raw_text": text,
                "refined_text": text
            })
            idx += 1

    return raw_segments


def transcribe_audio(
    audio_path: Path,
    progress_callback: Optional[Callable[[float, float], None]] = None
) -> List[Dict[str, Any]]:
    """
    Transcribes audio using faster-whisper with word-level timestamps,
    automatic runtime CUDA OOM -> CPU(int8) fallback, and hallucination deduplication.
    """
    logger.info(f"Starting STT transcription on {audio_path}")
    model = get_whisper_model(force_cpu=False)

    try:
        raw_segments = _run_transcribe_pass(model, audio_path, progress_callback=progress_callback)
    except Exception as e:
        err_lower = str(e).lower()
        is_cuda_active = bool(_loaded_whisper_sig and _loaded_whisper_sig[1] == "cuda")
        is_cuda_err = any(k in err_lower for k in ("cuda", "out of memory", "cublas", "cudnn", "alloc", "device", "oom"))
        if is_cuda_active or is_cuda_err:
            logger.warning(
                f"CUDA runtime/OOM error during Whisper STT ({e}). "
                f"Unloading GPU model and retrying automatically on CPU (compute_type='int8')..."
            )
            unload_whisper_model()
            cpu_model = get_whisper_model(force_cpu=True)
            raw_segments = _run_transcribe_pass(cpu_model, audio_path, progress_callback=progress_callback)
        else:
            unload_whisper_model()
            raise

    # Merge or filter standalone elongation/punctuation tokens like 'ー'
    cleaned_segments = []
    for seg in raw_segments:
        rt = (seg.get("raw_text") or "").strip()
        if rt in ("ー", "〜", "~", "-", "っ", "ッ") and cleaned_segments:
            prev = cleaned_segments[-1]
            prev["raw_text"] = prev["raw_text"] + rt
            prev["refined_text"] = prev["raw_text"]
            prev["end"] = max(prev["end"], seg["end"])
            prev["end_time_str"] = format_timestamp(prev["end"])
        elif rt not in ("ー", "〜", "~", "-"):
            seg["index"] = len(cleaned_segments) + 1
            cleaned_segments.append(seg)

    # Deduplicate consecutive/looping BGM hallucinations
    cleaned_segments = _deduplicate_hallucinations(cleaned_segments)
    for idx_num, seg in enumerate(cleaned_segments, start=1):
        seg["index"] = idx_num

    # Free Whisper GPU VRAM before LLM refinement starts
    unload_whisper_model()

    # Keep raw timestamps intact until LLM refinement finishes (routes.py applies optimize_subtitle_timing after LLM)
    logger.info(f"Transcription complete: extracted {len(cleaned_segments)} clean segments.")
    return cleaned_segments
