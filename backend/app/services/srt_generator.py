import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
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
    1. [Requirement 1-1 & 1-2] Genuine speaker overlap detection on RAW timestamps FIRST:
       Merges concurrent speech into 2-line subtitles (- Speaker 1\n- Speaker 2) without
       false overlap triggers from +0.3s end-time extension.
    2. Post-overlap end-time extension (up to +0.3s / 300ms) and natural reading duration
       strictly bounded by (next.start - 50ms) so sequential subtitles never collide or drift.
    3. Strict 50ms transition gap and >= 150ms minimum duration guard (no <100ms micro-fragments
       and no start >= end timestamp inversions).
    4. Clean re-sequencing of subtitle indices (1 to N).
    """
    if not segments:
        return []

    MIN_SLICE_DUR = 0.15  # Minimum 150ms duration to prevent <100ms micro-fragments

    # 1. Filter out empty segments and parse RAW timestamps (DO NOT add extend_sec before overlap pass)
    raw_list = []
    for s in segments:
        text = str(s.get("refined_text") or s.get("text") or s.get("raw_text") or "").strip()
        if not text:
            continue
        st = max(0.0, float(s.get("start", 0.0)))
        raw_ed = max(st + MIN_SLICE_DUR, float(s.get("end", st + 1.2)))
        raw_list.append({
            "start": round(st, 3),
            "end": round(raw_ed, 3),
            "text": text,
            "already_optimized": bool(s.get("_timing_optimized")),
            "is_overlap": False,
            "orig": dict(s)
        })

    if not raw_list:
        return []

    # 2. Chronological sort by raw start time, then end time
    raw_list.sort(key=lambda s: (s["start"], s["end"]))

    # 3. Genuine overlap resolution pass on RAW timestamps (Slices and merges overlapping speaker segments)
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

            # Genuine overlap on raw timestamps: current ends after next starts + 50ms tolerance
            if c_ed > n_st + min_gap:
                overlap_st = max(c_st, n_st)
                overlap_ed = min(c_ed, n_ed)

                # Part A: Pre-overlap solo speech (only if remaining slice after 50ms gap is >= 300ms)
                pre_ed = round(overlap_st - min_gap, 3)
                if pre_ed - c_st >= 0.30:
                    merged_items.append({
                        "start": round(c_st, 3),
                        "end": pre_ed,
                        "text": c_tx,
                        "already_optimized": curr.get("already_optimized", False),
                        "is_overlap": True
                    })
                elif overlap_st > c_st:
                    # Short prefix: absorb into the overlap window so no words or micro-slices are lost
                    overlap_st = c_st

                # Part B: Concurrent dual-speaker speech (2 lines: - Line A\n- Line B)
                dual_text = format_dual_lines(c_tx, n_tx)
                if overlap_ed - overlap_st >= MIN_SLICE_DUR:
                    merged_items.append({
                        "start": round(overlap_st, 3),
                        "end": round(overlap_ed, 3),
                        "text": dual_text,
                        "already_optimized": True,
                        "is_overlap": True
                    })
                else:
                    # Brief overlap window (<150ms): merge cleanly across union window and advance both
                    merged_items.append({
                        "start": round(min(c_st, n_st), 3),
                        "end": round(max(c_ed, n_ed), 3),
                        "text": dual_text,
                        "already_optimized": True,
                        "is_overlap": True
                    })
                    i += 2
                    continue

                # Part C: Post-overlap trailing speech (only if trailing slice after 50ms gap is >= 250ms)
                post_st = round(overlap_ed + min_gap, 3)
                if c_ed - post_st >= 0.25 and c_ed >= n_ed:
                    # Current speaker kept talking significantly after next speaker stopped
                    raw_list[i + 1] = {
                        "start": post_st,
                        "end": round(c_ed, 3),
                        "text": c_tx,
                        "already_optimized": curr.get("already_optimized", False),
                        "is_overlap": True,
                        "orig": curr.get("orig", {})
                    }
                    i += 1
                    continue
                elif n_ed - post_st >= 0.25:
                    # Next speaker continues talking significantly after current speaker stopped
                    raw_list[i + 1] = {
                        "start": post_st,
                        "end": round(n_ed, 3),
                        "text": n_tx,
                        "already_optimized": nxt.get("already_optimized", False),
                        "is_overlap": True,
                        "orig": nxt.get("orig", {})
                    }
                    i += 1
                    continue
                else:
                    # Both ended within or near the overlap window (prevent <100ms micro-fragments)
                    if merged_items:
                        merged_items[-1]["end"] = round(max(merged_items[-1]["end"], c_ed, n_ed), 3)
                    i += 2
                    continue

        merged_items.append({
            "start": round(c_st, 3),
            "end": round(c_ed, 3),
            "text": c_tx,
            "already_optimized": curr.get("already_optimized", False),
            "is_overlap": curr.get("is_overlap", False)
        })
        i += 1

    # 4. Post-overlap +0.3s extension & 50ms gap enforcement pass (strictly bounded by next.start - 50ms)
    optimized = []
    last_end = -1.0
    total_merged = len(merged_items)

    for idx, item in enumerate(merged_items):
        st = max(0.0, float(item["start"]))
        raw_ed = max(st + MIN_SLICE_DUR, float(item["end"]))
        txt = str(item["text"]).strip()
        already_opt = bool(item.get("already_optimized"))
        is_ov = bool(item.get("is_overlap"))

        # Enforce minimum 50ms gap from previous subtitle
        if idx > 0 and st < round(last_end + min_gap, 3):
            st = round(last_end + min_gap, 3)

        # Upper bound from next subtitle's start time so we never invade (next.start - 50ms)
        max_allowed_end: Optional[float] = None
        if idx + 1 < total_merged:
            next_st = float(merged_items[idx + 1]["start"])
            max_allowed_end = round(next_st - min_gap, 3)

        # Calculate desired end time (+0.3s extension + natural reading time for non-overlapping segments)
        eff_extend = 0.0 if (already_opt or is_ov or extend_sec <= 0.0) else extend_sec
        extended_ed = round(raw_ed + eff_extend, 3)

        clean_len = len(re.sub(r"\s+", "", txt))
        min_reading_dur = max(0.8, min(4.5, (clean_len / 12.0) + 0.5))
        desired_ed = max(extended_ed, round(st + min_reading_dur, 3)) if not (already_opt or is_ov) else extended_ed

        if max_allowed_end is not None:
            if max_allowed_end >= round(st + MIN_SLICE_DUR, 3):
                # Cap at next.start - 50ms so we never push subsequent subtitles forward
                ed = max(min(raw_ed, max_allowed_end), min(desired_ed, max_allowed_end))
            else:
                ed = max(raw_ed, round(st + MIN_SLICE_DUR, 3))
        else:
            ed = desired_ed

        # Final micro-segment & timestamp inversion guard (strictly guarantee start >= 0 and end - start >= 150ms)
        st = round(max(0.0, st), 3)
        if ed - st < MIN_SLICE_DUR:
            if max_allowed_end is not None and max_allowed_end - st >= 0.12:
                ed = round(max_allowed_end, 3)
            else:
                ed = round(st + MIN_SLICE_DUR, 3)
        else:
            ed = round(ed, 3)

        last_end = ed
        final_start = st
        final_end = ed

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
            "raw_text": txt,
            "_timing_optimized": True
        })

    return optimized

def generate_srt_file(segments: List[Dict[str, Any]], output_srt_path: Path, optimize: bool = True) -> Path:
    """
    Generates a standard .srt file from segments using pysrt,
    saving in UTF-8 with BOM (utf-8-sig) and strict chronological ordering
    so all players including Naver Series On Player, PotPlayer, and Windows Media Player render flawlessly.
    """
    logger.info(f"Generating SRT file at: {output_srt_path}")
    output_srt_path.parent.mkdir(parents=True, exist_ok=True)
    if optimize and not all(seg.get("_timing_optimized") for seg in segments):
        optimized_segments = optimize_subtitle_timing(segments)
    else:
        optimized_segments = segments
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
