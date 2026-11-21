import gc
import logging
import subprocess
from pathlib import Path
from typing import Callable, Optional

from app.services.audio_extractor import AUDIO_ENHANCE_FILTER

logger = logging.getLogger(__name__)

DEFAULT_DEMUCS_MODEL = "htdemucs"


def is_vocal_separation_available() -> bool:
    """Returns True if torch, demucs, and soundfile are importable."""
    try:
        import torch  # noqa: F401
        import demucs.pretrained  # noqa: F401
        import demucs.apply  # noqa: F401
        import soundfile  # noqa: F401
        return True
    except Exception:
        return False


def _run_ffmpeg(cmd: list[str], desc: str) -> None:
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError as e:
        raw_stderr = e.stderr or b""
        err_msg = ""
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                err_msg = raw_stderr.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if not err_msg:
            err_msg = raw_stderr.decode("utf-8", errors="ignore")
        if "Output file does not contain any stream" in err_msg or "matches no streams" in err_msg or "does not contain any stream" in err_msg:
            raise ValueError(
                "오디오 추출 실패: 해당 동영상 파일에 오디오(음성) 트랙이 포함되어 있지 않습니다. "
                "(The provided video file does not contain an audio track.)"
            )
        tail = " | ".join([ln.strip() for ln in err_msg.splitlines() if ln.strip()][-4:])
        raise RuntimeError(f"FFmpeg {desc} failed: {tail}") from e


def _release_torch_vram() -> None:
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def separate_vocals_to_wav(
    video_path: Path,
    output_audio_path: Path,
    model_name: str = DEFAULT_DEMUCS_MODEL,
    prefer_cuda: bool = True,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Path:
    """
    Extracts raw 44.1kHz stereo audio from video_path, runs Demucs vocal separation
    (stripping BGM/OST accompaniment while preserving singing vocals and dialogue),
    and writes a 16kHz mono normalized WAV ready for faster-whisper STT.

    Automatically falls back from CUDA to CPU on CUDA OOM, and guarantees cleanup
    of GPU VRAM and all intermediate temporary WAV files.
    """
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    video_path = Path(video_path).resolve()
    output_audio_path = Path(output_audio_path).resolve()
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)

    stem_prefix = output_audio_path.stem
    raw_stereo_wav = output_audio_path.parent / f"{stem_prefix}_demucs_in44k.wav"
    vocals_stereo_wav = output_audio_path.parent / f"{stem_prefix}_demucs_vocals44k.wav"

    model = None
    try:
        if progress_callback:
            progress_callback("오디오 원음 추출 중 (Demucs 보컬 분리 준비)...")

        # 1. Extract raw 44.1kHz stereo WAV (unfiltered for clean harmonic separation)
        _run_ffmpeg(
            [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "44100",
                "-ac", "2",
                str(raw_stereo_wav),
            ],
            desc="44.1kHz stereo extraction",
        )

        # 2. Load stereo audio via soundfile (avoids torchaudio/torchcodec backend issues on Windows)
        wav_np, sr = sf.read(str(raw_stereo_wav), dtype="float32", always_2d=True)
        if wav_np.size == 0:
            raise RuntimeError("추출된 오디오 파일이 비어 있습니다.")
        if wav_np.shape[1] == 1:
            wav_np = np.repeat(wav_np, 2, axis=1)
        elif wav_np.shape[1] > 2:
            wav_np = wav_np[:, :2]

        wav_tensor = torch.from_numpy(wav_np.T.copy())  # shape: (2, samples)
        del wav_np

        use_cuda = prefer_cuda and torch.cuda.is_available()
        device = torch.device("cuda" if use_cuda else "cpu")

        if progress_callback:
            dev_label = "GPU" if use_cuda else "CPU"
            progress_callback(f"Demucs ({model_name}) 보컬 분리 중 ({dev_label})...")

        logger.info(f"Loading Demucs model '{model_name}' on {device} for vocal separation...")
        model = get_model(model_name)
        model.eval()

        def _run_separation(target_device: "torch.device") -> "np.ndarray":
            model.to(target_device)
            # Normalize input for Demucs as in demucs.separate
            ref = wav_tensor.mean(0)
            ref_mean = ref.mean()
            ref_std = ref.std()
            if float(ref_std) < 1e-8:
                return wav_tensor.numpy()

            norm_wav = (wav_tensor - ref_mean) / ref_std
            with torch.no_grad():
                sources = apply_model(
                    model,
                    norm_wav.unsqueeze(0),
                    device=target_device,
                    shifts=1,
                    split=True,
                    overlap=0.25,
                    progress=False,
                )
            sources = sources * ref_std + ref_mean
            vocals_idx = model.sources.index("vocals") if "vocals" in model.sources else -1
            vocals_tensor = sources[0, vocals_idx].detach().cpu()
            del sources, norm_wav
            return vocals_tensor.numpy()

        try:
            vocals_np = _run_separation(device)
        except Exception as sep_err:
            err_lower = str(sep_err).lower()
            is_cuda_err = use_cuda and any(
                k in err_lower for k in ("cuda", "out of memory", "cublas", "cudnn", "alloc", "oom")
            )
            if is_cuda_err:
                logger.warning(f"CUDA error during Demucs vocal separation ({sep_err}). Retrying on CPU...")
                model.to("cpu")
                _release_torch_vram()
                if progress_callback:
                    progress_callback(f"Demucs ({model_name}) 보컬 분리 중 (CPU 폴백)...")
                vocals_np = _run_separation(torch.device("cpu"))
            else:
                raise

        del wav_tensor

        # 3. Save separated vocals stereo WAV and convert to 16kHz mono normalized WAV for Whisper
        vocals_np = np.clip(vocals_np, -1.0, 1.0)
        sf.write(str(vocals_stereo_wav), vocals_np.T, sr, subtype="PCM_16")
        del vocals_np

        if progress_callback:
            progress_callback("분리된 보컬 음량 정규화 중 (FFmpeg)...")

        try:
            _run_ffmpeg(
                [
                    "ffmpeg", "-y",
                    "-i", str(vocals_stereo_wav),
                    "-af", AUDIO_ENHANCE_FILTER,
                    "-acodec", "pcm_s16le",
                    "-ar", "16000",
                    "-ac", "1",
                    str(output_audio_path),
                ],
                desc="vocal 16kHz normalized conversion",
            )
        except Exception as e_filt:
            logger.warning(f"Filtered vocal normalization failed ({e_filt}), retrying plain 16kHz conversion...")
            _run_ffmpeg(
                [
                    "ffmpeg", "-y",
                    "-i", str(vocals_stereo_wav),
                    "-acodec", "pcm_s16le",
                    "-ar", "16000",
                    "-ac", "1",
                    str(output_audio_path),
                ],
                desc="vocal 16kHz plain conversion",
            )

        logger.info(f"Demucs vocal separation completed successfully: {output_audio_path}")
        return output_audio_path

    finally:
        if model is not None:
            try:
                model.to("cpu")
            except Exception:
                pass
            del model
        _release_torch_vram()
        for tmp_f in (raw_stereo_wav, vocals_stereo_wav):
            try:
                if tmp_f.exists():
                    tmp_f.unlink(missing_ok=True)
            except Exception as e_rm:
                logger.warning(f"Could not delete temp Demucs file {tmp_f}: {e_rm}")

