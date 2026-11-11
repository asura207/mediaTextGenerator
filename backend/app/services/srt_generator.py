import re
import logging
from pathlib import Path
from typing import List, Dict, Any
import pysrt

logger = logging.getLogger(__name__)

def format_timestamp(seconds: float) -> str:
    """Formats seconds to standard SRT timestamp: HH:MM:SS,mmm with carry-over protection."""
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours = total_ms // 3600000
    minutes = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def seconds_to_subrip_time(seconds: float) -> pysrt.SubRipTime:
    """Converts seconds (float) to pysrt.SubRipTime safely using milliseconds."""
    ms = max(0, int(round(float(seconds) * 1000)))
    return pysrt.SubRipTime.from_ordinal(ms)

def optimize_subtitle_timing(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Optimizes subtitle segment start and end times so that:
    1. Segments are strictly sorted in chronological order (start ASC), preventing timeline skips.
    2. Subtitles disappear promptly when speech/dialogue finishes.
    3. Subtitles never artificially linger across long pauses or musical interludes.
    4. Each subtitle remains visible for an appropriate reading duration:
       - Minimum duration: ~1.2s to 1.4s (ensures readability for short 1-word lines like '네', '고마워').
       - Maximum duration: capped at ~5.5s to 6.0s (broadcast / Netflix standard).
    5. Consecutive subtitles NEVER overlap; a clean 50ms transition gap is guaranteed
       via forward-cascade timeline correction so strict players (Series On, TV, etc.) never drop subtitles.
    6. Indices are re-sequenced cleanly from 1 to N without gaps.
    """
    if not segments:
        return []

    # 1. Filter out empty or whitespace-only segments
    valid_segments = []
    for s in segments:
        text = str(s.get("refined_text") or s.get("text") or s.get("raw_text") or "").strip()
        if text:
            valid_segments.append(dict(s))

    if not valid_segments:
        return []

    # 2. Strictly sort by start time to prevent Series On Player timeline skip bugs!
    valid_segments.sort(key=lambda s: (float(s.get("start", 0.0)), float(s.get("end", 0.0))))

    num_segs = len(valid_segments)
    optimized = []

    # 3. Forward cascade pass: guarantees zero overlap, >= 50ms transition gap, and readability duration
    for i in range(num_segs):
        seg = dict(valid_segments[i])
        cur_start = max(0.0, float(seg.get("start", 0.0)))
        raw_end = float(seg.get("end", cur_start + 1.5))
        text = str(seg.get("refined_text") or seg.get("text") or seg.get("raw_text") or "").strip()

        # Clean length without whitespace
        clean_len = len(re.sub(r"\s+", "", text))

        # Natural reading duration: ~10-12 CPS + base buffer
        natural_dur = max(1.2, min(5.8, (clean_len / 10.0) + 0.8))
        raw_dur = max(0.4, raw_end - cur_start)
        threshold = max(natural_dur * 1.3, min(3.5, natural_dur + 1.0))

        if raw_dur > threshold:
            target_dur = natural_dur
        else:
            target_dur = min(raw_dur, natural_dur + 0.5)

        if i + 1 < num_segs:
            next_start = float(valid_segments[i + 1].get("start", cur_start + 0.5))
            # If next subtitle starts too early, push it forward to give current subtitle room
            if next_start < cur_start + 0.35:
                next_start = cur_start + 0.35
                valid_segments[i + 1]["start"] = next_start

            # Maintain strict 50ms transition gap before next subtitle begins
            cur_end = min(cur_start + target_dur, next_start - 0.05)
            cur_end = max(cur_start + 0.25, cur_end)

            if cur_end >= next_start:
                valid_segments[i + 1]["start"] = cur_end + 0.05
        else:
            cur_end = max(cur_start + 0.25, cur_start + target_dur)

        final_start = round(cur_start, 3)
        final_end = round(cur_end, 3)

        seg["index"] = i + 1
        seg["start"] = final_start
        seg["end"] = final_end
        formatted_start = format_timestamp(final_start)
        formatted_end = format_timestamp(final_end)
        seg["start_str"] = formatted_start
        seg["end_str"] = formatted_end
        seg["start_time_str"] = formatted_start
        seg["end_time_str"] = formatted_end
        optimized.append(seg)

    return optimized

def generate_srt_file(segments: List[Dict[str, Any]], output_srt_path: Path) -> Path:
    """
    Generates a standard .srt file from segments using pysrt,
    saving in UTF-8 with BOM (utf-8-sig) and strict chronological ordering
    so all players including Naver Series On Player, PotPlayer, and Windows Media Player render flawlessly.
    """
    logger.info(f"Generating SRT file at: {output_srt_path}")
    output_srt_path.parent.mkdir(parents=True, exist_ok=True)
    optimized_segments = optimize_subtitle_timing(segments)
    subs = pysrt.SubRipFile()
    
    for i, seg in enumerate(optimized_segments, start=1):
        start_secs = float(seg.get("start", 0.0))
        end_secs = float(seg.get("end", start_secs + 1.0))
        text = seg.get("refined_text") or seg.get("text") or seg.get("raw_text") or ""
        
        start_time = seconds_to_subrip_time(start_secs)
        end_time = seconds_to_subrip_time(end_secs)
        
        item = pysrt.SubRipItem(
            index=i,
            start=start_time,
            end=end_time,
            text=str(text).strip()
        )
        subs.append(item)
        
    # Save as UTF-8 with BOM (utf-8-sig) for universal player compatibility
    subs.save(str(output_srt_path), encoding='utf-8-sig')
    logger.info(f"SRT file generated successfully with UTF-8 BOM ({len(subs)} entries).")
    return output_srt_path
