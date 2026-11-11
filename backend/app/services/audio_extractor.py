import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def _extract_audio_ffmpeg(video_path: Path, output_audio_path: Path) -> Path:
    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-vn",
        "-af", "dynaudnorm=f=75:g=25:p=0.95:m=10.0",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_audio_path),
        "-y"
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        logger.info("Audio extracted successfully with dynamic loudness normalization via ffmpeg.")
        return output_audio_path
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.decode("utf-8", errors="ignore")
        if "Output file does not contain any stream" in err_msg or "matches no streams" in err_msg:
            raise ValueError("오디오 추출 실패: 해당 동영상 파일에 오디오(음성) 트랙이 포함되어 있지 않습니다. (The provided video file does not contain an audio track.)")
        # Extract concise error lines instead of full ffmpeg build configuration banner
        err_lines = [line.strip() for line in err_msg.splitlines() if line.strip()]
        tail_err = " | ".join(err_lines[-4:]) if err_lines else err_msg
        logger.error(f"FFmpeg audio extraction failed: {tail_err}")
        raise RuntimeError(f"Audio extraction failed: {tail_err}")
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Failed to extract audio: {str(e)}")
        raise RuntimeError(f"Audio extraction error: {str(e)}")


def extract_audio(video_path: Path, output_audio_path: Path) -> Path:
    """
    Extracts audio from video file to .wav format using ffmpeg with dynamic loudness normalization.
    Automatically amplifies quiet/whispered speech while preventing loud clipping.
    Recommended audio specs for Whisper: 16kHz mono WAV.
    """
    logger.info(f"Extracting audio from {video_path} to {output_audio_path}")
    
    # Fast path: High-performance FFmpeg with dynaudnorm dynamic volume normalization
    try:
        return _extract_audio_ffmpeg(video_path, output_audio_path)
    except ValueError as ve:
        logger.warning(f"Video has no audio track ({ve}), skipping MoviePy fallback.")
        raise RuntimeError(str(ve))
    except Exception as e:
        logger.warning(f"Direct FFmpeg extraction failed ({e}), attempting MoviePy fallback...")

    # Fallback: MoviePy
    try:
        try:
            from moviepy.editor import VideoFileClip
        except ImportError:
            from moviepy import VideoFileClip
            
        with VideoFileClip(str(video_path)) as video:
            if video.audio is None:
                raise ValueError("오디오 추출 실패: 해당 동영상 파일에 오디오(음성) 트랙이 포함되어 있지 않습니다. (The provided video file does not contain an audio track.)")
            video.audio.write_audiofile(
                str(output_audio_path),
                fps=16000,
                nbytes=2,
                codec='pcm_s16le',
                ffmpeg_params=["-ac", "1", "-af", "dynaudnorm=f=75:g=25:p=0.95:m=10.0"],
                logger=None
            )
        logger.info("Audio extracted successfully via moviepy.")
        return output_audio_path
    except Exception as e:
        logger.warning(f"MoviePy extraction failed ({e}), re-raising...")
        raise RuntimeError(f"Audio extraction failed: {e}")

