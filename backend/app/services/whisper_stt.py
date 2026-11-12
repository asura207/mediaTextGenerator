import os
import sys
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
_whisper_model: WhisperModel = None
_loaded_whisper_sig = None

def get_whisper_model() -> WhisperModel:
    global _whisper_model, _loaded_whisper_sig
    cfg = get_whisper_config()
    model_size = cfg["model_size"]
    device = cfg["device"]
    compute_type = cfg["compute_type"]
    current_sig = (model_size, device, compute_type)

    if _whisper_model is None or _loaded_whisper_sig != current_sig:
        try:
            logger.info(f"Loading faster-whisper ({device}): model={model_size}, compute_type={compute_type}")
            _whisper_model = WhisperModel(
                model_size_or_path=model_size,
                device=device,
                compute_type=compute_type
            )
            _loaded_whisper_sig = current_sig
            logger.info(f"Whisper model '{model_size}' successfully loaded on {device}.")
        except Exception as e:
            logger.warning(f"Failed to load Whisper '{model_size}' on {device} ({e}). Falling back to CPU...")
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


def transcribe_audio(
    audio_path: Path,
    progress_callback: Optional[Callable[[float, float], None]] = None
) -> List[Dict[str, Any]]:
    """
    Transcribes audio using faster-whisper with word-level timestamps,
    splitting long silences and ensuring subtitles disappear when dialogue ends.
    """
    logger.info(f"Starting STT transcription on {audio_path}")
    model = get_whisper_model()
    
    # Transcribe with ultra-high sensitivity for soft dialogue, moans, screams, and non-verbal vocalizations
    segments_generator, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(
            threshold=0.10,              # Lowered from 0.25 -> 0.10: Captures subtle moans, whispers, crying, and screams
            min_silence_duration_ms=1000,# Extended from 500ms -> 1000ms: Prevents cutting mid-breath or between moans
            speech_pad_ms=600            # Increased from 400ms -> 600ms: Protects initial gasps and trailing exhalations
        ),
        no_speech_threshold=0.65,         # Raised from 0.4 -> 0.65: Prevents Whisper from prematurely discarding emotional non-verbal vocalizations
        log_prob_threshold=-1.0,          # faster-whisper keyword is log_prob_threshold (with underscore)
        compression_ratio_threshold=2.4,
        condition_on_previous_text=False, # Independent decoding avoids silence hallucination cascading
        initial_prompt="ああ、あっ、うっ、んっ、きゃあ、はぁ、いや、痛い、すごい、やめて、だめ… 아, 앗, 으윽, 꺄악, 하아, 싫어, 아파, 흑... Oh, Ah, Ugh, Wow"
    )
    
    logger.info(f"Detected language '{info.language}' with probability {info.language_probability:.2f}")

    total_duration = getattr(info, "duration", None) or 1.0
    last_reported_sec = -10.0

    raw_segments = []
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
            current_words = [words[0]]
            for w in words[1:]:
                gap = w.start - current_words[-1].end
                if gap > 1.8:
                    sub_text = "".join(x.word for x in current_words).strip()
                    if sub_text:
                        raw_segments.append({
                            "index": idx,
                            "start": round(current_words[0].start, 3),
                            "end": round(current_words[-1].end + 0.35, 3),
                            "start_time_str": format_timestamp(current_words[0].start),
                            "end_time_str": format_timestamp(current_words[-1].end + 0.35),
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
                    raw_segments.append({
                        "index": idx,
                        "start": round(current_words[0].start, 3),
                        "end": round(current_words[-1].end + 0.35, 3),
                        "start_time_str": format_timestamp(current_words[0].start),
                        "end_time_str": format_timestamp(current_words[-1].end + 0.35),
                        "raw_text": sub_text,
                        "refined_text": sub_text
                    })
                    idx += 1
        elif words and len(words) == 1:
            raw_segments.append({
                "index": idx,
                "start": round(words[0].start, 3),
                "end": round(words[0].end + 0.35, 3),
                "start_time_str": format_timestamp(words[0].start),
                "end_time_str": format_timestamp(words[0].end + 0.35),
                "raw_text": text,
                "refined_text": text
            })
            idx += 1
        else:
            raw_segments.append({
                "index": idx,
                "start": round(s.start, 3),
                "end": round(s.end, 3),
                "start_time_str": format_timestamp(s.start),
                "end_time_str": format_timestamp(s.end),
                "raw_text": text,
                "refined_text": text
            })
            idx += 1

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

    # Free Whisper GPU VRAM before LLM refinement starts
    unload_whisper_model()

    # Optimize timings across all segments so subtitles disappear when dialogue ends
    optimized_segments = optimize_subtitle_timing(cleaned_segments)
    logger.info(f"Transcription complete: extracted and optimized {len(optimized_segments)} segments.")
    return optimized_segments
