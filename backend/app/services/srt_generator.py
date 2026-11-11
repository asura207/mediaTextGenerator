import re
import logging
from pathlib import Path
from typing import List, Dict, Any
import pysrt

logger = logging.getLogger(__name__)

def format_timestamp(seconds: float) -> str:
    """Formats seconds to standard SRT timestamp: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def seconds_to_subrip_time(seconds: float) -> pysrt.SubRipTime:
    """Converts seconds (float) to pysrt.SubRipTime safely using milliseconds."""
    ms = int(round(max(0.0, float(seconds)) * 1000))
    return pysrt.SubRipTime.from_ordinal(ms)

def optimize_subtitle_timing(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Optimizes subtitle segment start and end times so that:
    1. Subtitles disappear promptly when speech/dialogue finishes.
    2. Subtitles never artificially linger across long pauses or musical interludes.
    3. Each subtitle remains visible for an appropriate reading duration:
       - Minimum duration: ~1.2s to 1.4s (ensures readability for short 1-word lines like '네', '고마워').
       - Maximum duration: capped at ~5.5s to 6.0s (broadcast / Netflix standard).
    4. Consecutive subtitles do not overlap; if the next speech starts immediately,
       a clean 50ms transition gap is maintained.
    """
    if not segments:
        return []

    optimized = []
    num_segs = len(segments)

    for i in range(num_segs):
        seg = dict(segments[i])
        start = float(seg.get("start", 0.0))
        raw_end = float(seg.get("end", start + 2.0))
        text = str(seg.get("refined_text") or seg.get("text") or seg.get("raw_text") or "").strip()

        # Clean length without whitespace
        clean_len = len(re.sub(r"\s+", "", text))

        # Natural reading duration: ~10-12 CPS + base buffer
        # e.g. 5 chars -> ~1.3s, 15 chars -> ~2.3s, 30 chars -> ~3.8s, 45+ chars -> ~5.5s
        natural_dur = max(1.2, min(5.8, (clean_len / 10.0) + 0.8))

        # Check raw duration given by STT / Whisper
        raw_dur = max(0.5, raw_end - start)

        # Threshold above which a subtitle is considered "hanging across silence"
        threshold = max(natural_dur * 1.3, min(3.5, natural_dur + 1.0))

        if raw_dur > threshold:
            # Dialogue has ended much earlier! Disappear naturally.
            target_dur = natural_dur
        else:
            # Reasonable duration - preserve raw end with a small natural breath buffer
            target_dur = min(raw_dur, natural_dur + 0.5)

        target_end = start + target_dur

        # Ensure no overlap with the next segment
        if i + 1 < num_segs:
            next_start = float(segments[i + 1].get("start", 0.0))
            if next_start > start:
                if target_end >= next_start - 0.05:
                    end = max(start + 0.6, next_start - 0.05)
                else:
                    end = target_end
            else:
                end = target_end
        else:
            end = target_end

        seg["start"] = round(start, 3)
        seg["end"] = round(end, 3)
        formatted_start = format_timestamp(start)
        formatted_end = format_timestamp(end)
        seg["start_str"] = formatted_start
        seg["end_str"] = formatted_end
        seg["start_time_str"] = formatted_start
        seg["end_time_str"] = formatted_end
        optimized.append(seg)

    return optimized

def generate_srt_file(segments: List[Dict[str, Any]], output_srt_path: Path) -> Path:
    """
    Generates a standard .srt file from segments using pysrt,
    ensuring subtitle end times properly disappear when dialogue finishes.
    """
    logger.info(f"Generating SRT file at: {output_srt_path}")
    optimized_segments = optimize_subtitle_timing(segments)
    subs = pysrt.SubRipFile()
    
    for i, seg in enumerate(optimized_segments, start=1):
        start_secs = float(seg.get("start", 0.0))
        end_secs = float(seg.get("end", start_secs + 1.0))
        text = seg.get("refined_text") or seg.get("text") or seg.get("raw_text") or ""
        
        start_time = seconds_to_subrip_time(start_secs)
        end_time = seconds_to_subrip_time(end_secs)
        
        index = seg.get("index") or i
        item = pysrt.SubRipItem(
            index=int(index),
            start=start_time,
            end=end_time,
            text=str(text).strip()
        )
        subs.append(item)
        
    subs.save(str(output_srt_path), encoding='utf-8')
    logger.info(f"SRT file generated successfully ({len(subs)} entries).")
    return output_srt_path
