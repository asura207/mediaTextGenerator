import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

AUDIO_ENHANCE_FILTER = "highpass=f=80,lowpass=f=8000,dynaudnorm=f=150:g=15:p=0.95:m=10.0"


def _extract_audio_ffmpeg(video_path: Path, output_audio_path: Path, use_filter: bool = True) -> Path:
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    src_path_str = str(Path(video_path).resolve())
    out_path_str = str(Path(output_audio_path).resolve())

    cmd = [
        "ffmpeg",
        "-y",
        "-i", src_path_str,
        "-vn",
    ]
    if use_filter:
        cmd.extend(["-af", AUDIO_ENHANCE_FILTER])
    cmd.extend([
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        out_path_str,
    ])
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        mode_desc = "with dynamic audio filter" if use_filter else "with plain fallback (no filter)"
        logger.info(f"Audio extracted successfully {mode_desc} via ffmpeg.")
        return output_audio_path
    except subprocess.CalledProcessError as e:
        if output_audio_path.exists():
            try:
                output_audio_path.unlink(missing_ok=True)
            except Exception:
                pass
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
            raise ValueError("오디오 추출 실패: 해당 동영상 파일에 오디오(음성) 트랙이 포함되어 있지 않습니다. (The provided video file does not contain an audio track.)")
        # Extract concise error lines instead of full ffmpeg build configuration banner
        err_lines = [line.strip() for line in err_msg.splitlines() if line.strip()]
        tail_err = " | ".join(err_lines[-4:]) if err_lines else err_msg
        logger.error(f"FFmpeg audio extraction failed (use_filter={use_filter}): {tail_err}")
        raise RuntimeError(f"Audio extraction failed: {tail_err}")
    except ValueError:
        if output_audio_path.exists():
            try:
                output_audio_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise
    except Exception as e:
        if output_audio_path.exists():
            try:
                output_audio_path.unlink(missing_ok=True)
            except Exception:
                pass
        logger.error(f"Failed to extract audio: {str(e)}")
        raise RuntimeError(f"Audio extraction error: {str(e)}")


def extract_audio(video_path: Path, output_audio_path: Path) -> Path:
    """
    Extracts audio from video file to .wav format using ffmpeg with dynamic loudness normalization
    (highpass=f=80,lowpass=f=8000,dynaudnorm=f=150:g=15:p=0.95:m=10.0).
    Automatically falls back to plain FFmpeg extraction (without -af filter) and then MoviePy if needed.
    Recommended audio specs for Whisper: 16kHz mono WAV.
    """
    logger.info(f"Extracting audio from {video_path} to {output_audio_path}")
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Fast path: High-performance FFmpeg with bandpass + dynaudnorm dynamic volume normalization
    try:
        return _extract_audio_ffmpeg(video_path, output_audio_path, use_filter=True)
    except ValueError as ve:
        logger.warning(f"Video has no audio track ({ve}), skipping fallbacks.")
        raise RuntimeError(str(ve))
    except Exception as e_filter:
        logger.warning(f"Filtered FFmpeg extraction failed ({e_filter}), retrying plain FFmpeg without -af filter...")

    # 2. Fallback 1: Plain FFmpeg extraction without -af filter (handles edge-case filter/stream incompatibilities)
    try:
        return _extract_audio_ffmpeg(video_path, output_audio_path, use_filter=False)
    except ValueError as ve:
        logger.warning(f"Video has no audio track ({ve}), skipping MoviePy fallback.")
        raise RuntimeError(str(ve))
    except Exception as e_plain:
        logger.warning(f"Plain FFmpeg extraction failed ({e_plain}), attempting MoviePy fallback...")

    # 3. Fallback 2: MoviePy
    try:
        try:
            from moviepy.editor import VideoFileClip
        except ImportError:
            from moviepy import VideoFileClip

        with VideoFileClip(str(Path(video_path).resolve())) as video:
            if video.audio is None:
                raise ValueError("오디오 추출 실패: 해당 동영상 파일에 오디오(음성) 트랙이 포함되어 있지 않습니다. (The provided video file does not contain an audio track.)")
            video.audio.write_audiofile(
                str(Path(output_audio_path).resolve()),
                fps=16000,
                nbytes=2,
                codec='pcm_s16le',
                ffmpeg_params=["-ac", "1"],
                logger=None
            )
        logger.info("Audio extracted successfully via moviepy.")
        return output_audio_path
    except Exception as e:
        if output_audio_path.exists():
            try:
                output_audio_path.unlink(missing_ok=True)
            except Exception:
                pass
        logger.warning(f"MoviePy extraction failed ({e}), re-raising...")
        raise RuntimeError(f"Audio extraction failed: {e}")

