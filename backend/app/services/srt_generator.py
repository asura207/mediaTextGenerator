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

def format_dual_lines(text_a: str, text_b: str) -> str:
    """Formats two overlapping speaker lines as standard dual-line dialog (- Line 1\n- Line 2)."""
    a = str(text_a or "").strip()
    b = str(text_b or "").strip()
    if not a:
        return b
    if not b:
        return a
    if a == b:
        return a

    lines = []
    for txt in (a, b):
        sub_lines = [l.strip() for l in txt.split("\n") if l.strip()]
        for sl in sub_lines:
            if sl.startswith(("-", "―", "—", "•", "·")):
                lines.append(sl)
            else:
                lines.append(f"- {sl}")
    return "\n".join(lines)


def optimize_subtitle_timing(
    segments: List[Dict[str, Any]],
    extend_sec: float = 0.3,
    min_gap: float = 0.05
) -> List[Dict[str, Any]]:
    """
    Optimizes subtitle timings with:
    1. [Requirement 1-1] End time extension (+0.3s / 300ms) for comfortable reading.
    2. [Requirement 1-2] Speaker overlap resolution: Merges concurrent speech into 2-line subtitles (- Speaker 1\n- Speaker 2).
    3. Strict 50ms transition gap between consecutive subtitles to prevent Series On / PotPlayer flickering/skips.
    4. Guard against negative durations or inverted timestamps (start < end strictly guaranteed).
    5. Clean re-sequencing of subtitle indices (1 to N).
    """
    if not segments:
        return []

    # 1. Filter out empty segments and parse clean floats
    raw_list = []
    for s in segments:
        text = str(s.get("refined_text") or s.get("text") or s.get("raw_text") or "").strip()
        if not text:
            continue
        st = max(0.0, float(s.get("start", 0.0)))
        # Apply +0.3s extension to original end
        raw_ed = float(s.get("end", st + 1.2))
        ed = max(st + 0.35, raw_ed + extend_sec)
        raw_list.append({
            "start": round(st, 3),
            "end": round(ed, 3),
            "text": text,
            "orig": dict(s)
        })

    if not raw_list:
        return []

    # 2. Chronological sort by start time
    raw_list.sort(key=lambda s: (s["start"], s["end"]))

    # 3. Overlap resolution pass (Slices and merges overlapping speaker segments)
    merged_items = []
    i = 0
    while i < len(raw_list):
        curr = raw_list[i]
        c_st = curr["start"]
        c_ed = curr["end"]
        c_tx = curr["text"]

        if i + 1 < len(raw_list):
            nxt = raw_list[i + 1]
            n_st = nxt["start"]
            n_ed = nxt["end"]
            n_tx = nxt["text"]

            # Check if current segment overlaps with next segment
            if c_ed > n_st + min_gap:
                overlap_st = n_st
                overlap_ed = min(c_ed, n_ed)

                # Part A: Pre-overlap solo speech (if long enough to read)
                if overlap_st - c_st >= 0.35:
                    merged_items.append({
                        "start": c_st,
                        "end": round(overlap_st - min_gap, 3),
                        "text": c_tx
                    })
                elif overlap_st > c_st:
                    # Very short prefix: shift overlap start earlier to avoid losing words
                    overlap_st = c_st

                # Part B: Concurrent dual-speaker speech (2 lines: - Line A\n- Line B)
                if overlap_ed > overlap_st + 0.2:
                    dual_text = format_dual_lines(c_tx, n_tx)
                    merged_items.append({
                        "start": round(overlap_st, 3),
                        "end": round(overlap_ed, 3),
                        "text": dual_text
                    })

                # Part C: Post-overlap trailing speech
                if c_ed > n_ed + min_gap:
                    # Current speaker kept talking after next speaker stopped
                    raw_list[i + 1] = {
                        "start": round(overlap_ed + min_gap, 3),
                        "end": c_ed,
                        "text": c_tx,
                        "orig": curr.get("orig", {})
                    }
                    i += 1
                    continue
                elif n_ed > c_ed + min_gap:
                    # Next speaker continues talking after current speaker stopped
                    raw_list[i + 1] = {
                        "start": round(overlap_ed + min_gap, 3),
                        "end": n_ed,
                        "text": n_tx,
                        "orig": nxt.get("orig", {})
                    }
                    i += 1
                    continue
                else:
                    # Both ended simultaneously
                    i += 2
                    continue

        merged_items.append({
            "start": round(c_st, 3),
            "end": round(c_ed, 3),
            "text": c_tx
        })
        i += 1

    # 4. Final smoothing & 50ms gap enforcement pass
    optimized = []
    last_end = -1.0

    for idx, item in enumerate(merged_items):
        st = max(0.0, float(item["start"]))
        ed = max(st + 0.3, float(item["end"]))
        txt = str(item["text"]).strip()

        # Ensure minimum 50ms gap from previous subtitle
        if st < last_end + min_gap:
            st = round(last_end + min_gap, 3)
            if ed <= st + 0.25:
                ed = round(st + 0.35, 3)

        # Natural reading duration check
        clean_len = len(re.sub(r"\s+", "", txt))
        min_reading_dur = max(0.8, min(5.0, (clean_len / 12.0) + 0.5))
        if ed - st < min_reading_dur:
            ed = round(st + min_reading_dur, 3)

        last_end = ed
        final_start = round(st, 3)
        final_end = round(ed, 3)

        start_str = format_timestamp(final_start)
        end_str = format_timestamp(final_end)

        optimized.append({
            "index": len(optimized) + 1,
            "start": final_start,
            "end": final_end,
            "start_str": start_str,
            "end_str": end_str,
            "start_time_str": start_str,
            "end_time_str": end_str,
            "text": txt,
            "refined_text": txt,
            "raw_text": txt
        })

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
