import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import pysrt

logger = logging.getLogger(__name__)

# Default timing engine constants in integer milliseconds (ms)
DEFAULT_EXTEND_MS = 300           # +0.3s (300ms) end-time extension
DEFAULT_MIN_GAP_MS = 50           # 50ms (0.05s) minimum transition gap between consecutive subtitles
DEFAULT_OVERLAP_THRESHOLD_MS = 150 # >= 150ms (0.15s) required to treat overlap as genuine 2-speaker overlap
DEFAULT_MIN_SOLO_MS = 350         # >= 350ms (0.35s) required to split pre/post solo segment instead of unifying
DEFAULT_MIN_DURATION_MS = 250     # >= 250ms (0.25s) minimum subtitle exposure duration
MAX_SPEAKER_LINES = 2             # Maximum 2 lines per subtitle segment

_LEADING_HYPHEN_RE = re.compile(r"^(?:[-―—•·]+\s*)+")


def to_ms(seconds: float) -> int:
    """Converts float seconds to non-negative integer milliseconds with exact rounding."""
    return max(0, int(round(float(seconds) * 1000.0)))


def to_sec(ms: int) -> float:
    """Converts integer milliseconds to float seconds rounded to 3 decimal places."""
    return round(int(ms) / 1000.0, 3)


def format_timestamp_ms(total_ms: int) -> str:
    """Formats integer milliseconds to standard SRT timestamp: HH:MM:SS,mmm."""
    ms = max(0, int(total_ms))
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    secs = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_timestamp(seconds: float) -> str:
    """Formats seconds to standard SRT timestamp: HH:MM:SS,mmm with carry-over protection."""
    return format_timestamp_ms(to_ms(seconds))


def seconds_to_subrip_time(seconds: float) -> pysrt.SubRipTime:
    """Converts seconds (float) to pysrt.SubRipTime safely using integer milliseconds."""
    return pysrt.SubRipTime.from_ordinal(to_ms(seconds))


def _strip_speaker_prefix(line: str) -> str:
    """Strips one or more leading hyphen/bullet prefixes (e.g. '- - 대사' -> '대사')."""
    return _LEADING_HYPHEN_RE.sub("", str(line or "").strip()).strip()


def normalize_subtitle_text(text: str) -> str:
    """
    Normalizes single-line or multi-line subtitle text:
    - Prevents duplicate hyphen prefixes ('- - 대사' -> '- 대사').
    - Deduplicates identical lines within the same subtitle.
    - Caps multi-line speaker subtitles at MAX_SPEAKER_LINES (2 lines).
    """
    raw = str(text or "").strip()
    if not raw:
        return ""

    raw_lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not raw_lines:
        return ""

    has_bullet = len(raw_lines) > 1 or any(_LEADING_HYPHEN_RE.match(l) for l in raw_lines)
    cleaned_lines: List[str] = []
    seen_norm: set[str] = set()

    for l in raw_lines:
        core = _strip_speaker_prefix(l)
        if not core:
            continue
        norm_key = re.sub(r"\s+", " ", core).lower()
        if norm_key in seen_norm:
            continue
        seen_norm.add(norm_key)
        cleaned_lines.append(core)

    if not cleaned_lines:
        return ""

    if len(cleaned_lines) == 1:
        # Single line: only keep '- ' if original explicitly had a single-line speaker prefix?
        # Standard single-speaker subtitles should not have a lone '- ' prefix.
        return cleaned_lines[0]

    # Enforce maximum 2 lines per subtitle segment so video is never obscured by 3-4 lines
    if len(cleaned_lines) > MAX_SPEAKER_LINES:
        head = cleaned_lines[0]
        tail = " / ".join(cleaned_lines[1:])
        cleaned_lines = [head, tail]

    if has_bullet or len(cleaned_lines) >= 2:
        return "\n".join(f"- {c}" for c in cleaned_lines)
    return "\n".join(cleaned_lines)


def format_dual_lines(text_a: str, text_b: str) -> str:
    """
    Formats two overlapping speaker utterances into standard 2-line dialogue:
      - 화자1 대사
      - 화자2 대사
    Strictly prevents duplicate '- - ' prefixes, duplicate identical utterances, and >2 lines.
    """
    utterances: List[str] = []
    seen_norm: set[str] = set()

    for raw_txt in (text_a, text_b):
        for sub_line in str(raw_txt or "").splitlines():
            core = _strip_speaker_prefix(sub_line)
            if not core:
                continue
            norm_key = re.sub(r"\s+", " ", core).lower()
            if norm_key in seen_norm:
                continue
            seen_norm.add(norm_key)
            utterances.append(core)

    if not utterances:
        return ""
    if len(utterances) == 1:
        return utterances[0]

    if len(utterances) > MAX_SPEAKER_LINES:
        utterances = [utterances[0], " / ".join(utterances[1:])]

    return "\n".join(f"- {u}" for u in utterances)


def optimize_subtitle_timing(
    segments: List[Dict[str, Any]],
    extend_sec: float = 0.3,
    min_gap: float = 0.05,
    overlap_threshold_sec: float = 0.15,
    min_solo_sec: float = 0.35,
    min_duration_sec: float = 0.25,
    apply_timing_optimization: bool = True,
) -> List[Dict[str, Any]]:
    """
    4-Stage Integer-Millisecond Subtitle Timing Engine:
      [Step 1] Raw Timestamp Normalization & Sorting (ms):
               Removes empty texts, fixes negative start (< 0 -> 0) and inverted/short durations (>= 250ms),
               and sorts chronologically by raw (start_ms, end_ms).
      [Step 2] Raw-Timestamp Speaker Overlap Resolution:
               - Micro-overlaps (< 150ms, e.g. Whisper VAD padding) are separated cleanly by a 50ms gap
                 (prev.end = curr.start - 50ms) WITHOUT false 2-line merging.
               - Genuine overlaps (>= 150ms) are merged into 2-line dialogue (- 화자1\n- 화자2).
               - Pre/post solo parts < 350ms are unified into the 2-line segment to prevent flickering fragments.
               - Solo parts >= 350ms are sliced cleanly with an exact 50ms transition gap.
      [Step 3] Clamped +0.3s (300ms) End-Time Extension:
               Extends each subtitle's end time by up to +300ms, strictly clamped at (next.start - 50ms)
               so it never invades the next subtitle or causes false overlaps / cascade drift.
      [Step 4] Final 50ms Transition Gap, Minimum Exposure Duration (250ms) & Sequential Indexing (1..N).
    """
    if not segments:
        return []

    extend_ms = to_ms(extend_sec) if apply_timing_optimization else 0
    gap_ms = to_ms(min_gap)
    overlap_threshold_ms = max(gap_ms, to_ms(overlap_threshold_sec))
    min_solo_ms = max(overlap_threshold_ms, to_ms(min_solo_sec))
    min_dur_ms = max(100, to_ms(min_duration_sec))

    # ==========================================================================
    # [Step 1] Raw Timestamp Normalization & Chronological Sorting (in ms)
    # ==========================================================================
    raw_list: List[Dict[str, Any]] = []
    for s in segments:
        raw_txt = str(s.get("refined_text") or s.get("text") or s.get("raw_text") or "").strip()
        clean_txt = normalize_subtitle_text(raw_txt)
        if not clean_txt:
            continue

        st_ms = to_ms(max(0.0, float(s.get("start", 0.0))))
        raw_end_val = s.get("end")
        if raw_end_val is None:
            ed_ms = st_ms + 1200
        else:
            ed_ms = to_ms(float(raw_end_val))
            if ed_ms <= st_ms:
                ed_ms = st_ms + 1200
            elif ed_ms - st_ms < min_dur_ms:
                ed_ms = st_ms + min_dur_ms

        already_opt = bool(s.get("_timing_optimized")) or (not apply_timing_optimization)
        is_dual = "\n" in clean_txt

        raw_list.append({
            "start_ms": st_ms,
            "end_ms": ed_ms,
            "text": clean_txt,
            "already_optimized": already_opt,
            "is_dual": is_dual,
            "clamped_by_slice": False,
            "orig": dict(s),
        })

    if not raw_list:
        return []

    raw_list.sort(key=lambda item: (item["start_ms"], item["end_ms"]))

    # ==========================================================================
    # [Step 2] Raw-Timestamp Speaker Overlap Detection & 2-Line Merge / Slicing
    # ==========================================================================
    if not apply_timing_optimization:
        step2_list = raw_list
    else:
        step2_list: List[Dict[str, Any]] = []
        i = 0
        while i < len(raw_list):
            curr = raw_list[i]
            c_st = curr["start_ms"]
            c_ed = curr["end_ms"]
            c_tx = curr["text"]

            if i + 1 < len(raw_list):
                nxt = raw_list[i + 1]
                n_st = nxt["start_ms"]
                n_ed = nxt["end_ms"]
                n_tx = nxt["text"]

                overlap_ms = c_ed - n_st

                # [2-1] Micro-overlap (< 150ms) OR already 2-line segment (prevent 3+ lines):
                # Separate cleanly with a 50ms transition gap instead of 2-line merging
                if overlap_ms >= 0 and (overlap_ms < overlap_threshold_ms or curr.get("is_dual") or nxt.get("is_dual")):
                    trimmed_c_ed = n_st - gap_ms
                    if trimmed_c_ed - c_st >= min_dur_ms:
                        curr["end_ms"] = trimmed_c_ed
                        curr["clamped_by_slice"] = True
                    else:
                        curr["end_ms"] = max(c_ed, c_st + min_dur_ms)
                        curr["clamped_by_slice"] = True
                        nxt["start_ms"] = curr["end_ms"] + gap_ms
                        if nxt["end_ms"] - nxt["start_ms"] < min_dur_ms:
                            nxt["end_ms"] = nxt["start_ms"] + min_dur_ms
                    step2_list.append(curr)
                    i += 1
                    continue

                # [2-2] Genuine speaker overlap (>= 150ms) between two single-speaker segments
                if overlap_ms >= overlap_threshold_ms:
                    dual_text = format_dual_lines(c_tx, n_tx)
                    # If both segments actually had identical text, unify into 1 segment
                    if "\n" not in dual_text:
                        step2_list.append({
                            "start_ms": min(c_st, n_st),
                            "end_ms": max(c_ed, n_ed),
                            "text": dual_text,
                            "already_optimized": curr["already_optimized"] and nxt["already_optimized"],
                            "is_dual": False,
                            "clamped_by_slice": False,
                            "orig": curr["orig"],
                        })
                        i += 2
                        continue

                    pre_solo_ms = n_st - c_st
                    post_solo_ms = abs(c_ed - n_ed)

                    # Only split pre-solo if raw lead-in >= 350ms AND remaining slice after 50ms gap >= 250ms
                    has_pre_solo = (pre_solo_ms >= min_solo_ms) and ((n_st - gap_ms - c_st) >= min_dur_ms)
                    # Only split post-solo if raw trailing difference >= 350ms AND remaining tail after 50ms gap >= 250ms
                    raw_overlap_ed = min(c_ed, n_ed)
                    max_ed = max(c_ed, n_ed)
                    has_post_solo = (post_solo_ms >= min_solo_ms) and ((max_ed - (raw_overlap_ed + gap_ms)) >= min_dur_ms)

                    # Complete overlap (both pre_solo < 350ms and post_solo < 350ms): unify without fragmentation
                    if not has_pre_solo and not has_post_solo:
                        step2_list.append({
                            "start_ms": min(c_st, n_st),
                            "end_ms": max_ed,
                            "text": dual_text,
                            "already_optimized": curr["already_optimized"] and nxt["already_optimized"],
                            "is_dual": True,
                            "clamped_by_slice": False,
                            "orig": curr["orig"],
                        })
                        i += 2
                        continue

                    # Partial overlap: slice solo and dual intervals with 50ms transition gaps
                    overlap_st = n_st if has_pre_solo else min(c_st, n_st)
                    overlap_ed = raw_overlap_ed if has_post_solo else max_ed

                    if has_pre_solo:
                        step2_list.append({
                            "start_ms": c_st,
                            "end_ms": overlap_st - gap_ms,
                            "text": c_tx,
                            "already_optimized": curr["already_optimized"],
                            "is_dual": False,
                            "clamped_by_slice": True,
                            "orig": curr["orig"],
                        })

                    # Ensure dual overlap segment itself is at least min_dur_ms
                    if overlap_ed - overlap_st < min_dur_ms:
                        overlap_ed = min(max_ed, overlap_st + min_dur_ms)

                    step2_list.append({
                        "start_ms": overlap_st,
                        "end_ms": overlap_ed,
                        "text": dual_text,
                        "already_optimized": curr["already_optimized"] and nxt["already_optimized"],
                        "is_dual": True,
                        "clamped_by_slice": has_post_solo,
                        "orig": curr["orig"],
                    })

                    if has_post_solo:
                        post_st = overlap_ed + gap_ms
                        if max_ed - post_st >= min_dur_ms:
                            if c_ed >= n_ed:
                                raw_list[i + 1] = {
                                    "start_ms": post_st,
                                    "end_ms": c_ed,
                                    "text": c_tx,
                                    "already_optimized": curr["already_optimized"],
                                    "is_dual": False,
                                    "clamped_by_slice": False,
                                    "orig": curr["orig"],
                                }
                            else:
                                raw_list[i + 1] = {
                                    "start_ms": post_st,
                                    "end_ms": n_ed,
                                    "text": n_tx,
                                    "already_optimized": nxt["already_optimized"],
                                    "is_dual": False,
                                    "clamped_by_slice": False,
                                    "orig": nxt["orig"],
                                }
                            i += 1
                            continue
                        else:
                            step2_list[-1]["end_ms"] = max_ed
                            step2_list[-1]["clamped_by_slice"] = False
                            i += 2
                            continue
                    else:
                        i += 2
                        continue

            step2_list.append(curr)
            i += 1

    # ==========================================================================
    # [Step 3] Clamped +0.3s (300ms) End-Time Extension
    #          seg.end = min(seg.end + 300ms, next.start - 50ms)
    # ==========================================================================
    total_step2 = len(step2_list)
    for idx, seg in enumerate(step2_list):
        if extend_ms > 0 and not seg.get("already_optimized") and not seg.get("clamped_by_slice"):
            desired_end_ms = seg["end_ms"] + extend_ms
            if idx + 1 < total_step2:
                max_allowed_end_ms = step2_list[idx + 1]["start_ms"] - gap_ms
                if max_allowed_end_ms > seg["end_ms"]:
                    seg["end_ms"] = min(desired_end_ms, max_allowed_end_ms)
            else:
                seg["end_ms"] = desired_end_ms

    # ==========================================================================
    # [Step 4] Final 50ms Transition Gap, Minimum Duration (250ms) & Indexing
    # ==========================================================================
    optimized: List[Dict[str, Any]] = []
    n_final = len(step2_list)

    for idx in range(n_final):
        seg = step2_list[idx]
        st_ms = max(0, int(seg["start_ms"]))
        ed_ms = int(seg["end_ms"])
        txt = normalize_subtitle_text(seg["text"])
        if not txt:
            continue

        # 1. Enforce >= 50ms gap after previous finalized subtitle
        if optimized:
            prev = optimized[-1]
            prev_st_ms = to_ms(prev["start"])
            prev_ed_ms = to_ms(prev["end"])
            if st_ms < prev_ed_ms + gap_ms:
                # First try trimming previous end if previous has room above min_dur_ms
                candidate_prev_ed = st_ms - gap_ms
                if candidate_prev_ed - prev_st_ms >= min_dur_ms:
                    prev_ed_ms = candidate_prev_ed
                    prev["end"] = to_sec(prev_ed_ms)
                    prev["end_str"] = format_timestamp_ms(prev_ed_ms)
                    prev["end_time_str"] = prev["end_str"]
                else:
                    # Otherwise advance current start to prev_ed_ms + gap_ms
                    st_ms = prev_ed_ms + gap_ms

        # 2. Enforce >= 50ms gap before next subtitle's start (if room allows min_dur_ms)
        if idx + 1 < n_final:
            next_st_ms = int(step2_list[idx + 1]["start_ms"])
            max_ed_ms = next_st_ms - gap_ms
            if ed_ms > max_ed_ms and max_ed_ms - st_ms >= min_dur_ms:
                ed_ms = max_ed_ms

        # 3. Guarantee minimum exposure duration (250ms) and strict start < end
        if ed_ms - st_ms < min_dur_ms:
            if idx + 1 < n_final:
                next_st_ms = int(step2_list[idx + 1]["start_ms"])
                if next_st_ms - gap_ms - st_ms >= 100:
                    ed_ms = max(ed_ms, min(st_ms + min_dur_ms, next_st_ms - gap_ms))
                else:
                    ed_ms = st_ms + min_dur_ms
            else:
                ed_ms = st_ms + min_dur_ms

        final_start_sec = to_sec(st_ms)
        final_end_sec = to_sec(ed_ms)
        start_str = format_timestamp_ms(st_ms)
        end_str = format_timestamp_ms(ed_ms)

        orig_dict = dict(seg.get("orig") or {})
        out_item: Dict[str, Any] = {
            **orig_dict,
            "index": len(optimized) + 1,
            "start": final_start_sec,
            "end": final_end_sec,
            "start_str": start_str,
            "end_str": end_str,
            "start_time_str": start_str,
            "end_time_str": end_str,
            "text": txt,
            "refined_text": txt,
            "raw_text": orig_dict.get("raw_text") or txt,
            "_timing_optimized": True,
        }
        optimized.append(out_item)

    return optimized


def generate_srt_file(
    segments: List[Dict[str, Any]],
    output_srt_path: Path,
    optimize: bool = True,
    apply_timing_optimization: bool = True,
) -> Path:
    """
    Generates a standard .srt file from segments using pysrt,
    saving in UTF-8 with BOM (utf-8-sig) and strict 1..N sequential indexing (clean_indexes)
    so Naver Series On Player, PotPlayer, and Windows Media Player render flawlessly.
    """
    logger.info(f"Generating SRT file at: {output_srt_path}")
    output_srt_path.parent.mkdir(parents=True, exist_ok=True)
    if optimize and not all(seg.get("_timing_optimized") for seg in segments):
        optimized_segments = optimize_subtitle_timing(
            segments,
            apply_timing_optimization=apply_timing_optimization,
        )
    else:
        optimized_segments = optimize_subtitle_timing(
            segments,
            extend_sec=0.0,
            apply_timing_optimization=False,
        )

    subs = pysrt.SubRipFile()

    for i, seg in enumerate(optimized_segments, start=1):
        st_ms = to_ms(float(seg.get("start", 0.0)))
        ed_ms = max(st_ms + 100, to_ms(float(seg.get("end", to_sec(st_ms + 1000)))))
        text = seg.get("refined_text") or seg.get("text") or seg.get("raw_text") or ""

        start_time = pysrt.SubRipTime.from_ordinal(st_ms)
        end_time = pysrt.SubRipTime.from_ordinal(ed_ms)

        item = pysrt.SubRipItem(
            index=i,
            start=start_time,
            end=end_time,
            text=str(text).strip(),
        )
        subs.append(item)

    # Guarantee sequential 1, 2, 3... numbering with zero gaps
    subs.clean_indexes()

    # Save as UTF-8 with BOM (utf-8-sig) for universal domestic player compatibility
    subs.save(str(output_srt_path), encoding="utf-8-sig")
    logger.info(f"SRT file generated successfully with UTF-8 BOM ({len(subs)} entries).")
    return output_srt_path
