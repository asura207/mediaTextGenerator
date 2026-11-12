import json
import logging
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from app.config import (
    OLLAMA_HOST,
    get_llm_batch_size,
    get_active_llm_provider,
    get_runtime_settings,
)
from app.database import get_all_dictionary_map
from app.services.llm_provider import chat_completion
from app.services.llm_refiner import (
    clean_json_response,
    extract_translations_from_parsed,
    extract_subtitles_via_regex,
    fast_translate_short,
    sanitize_subtitle_text,
    is_valid_korean_result,
)

logger = logging.getLogger(__name__)

RE_CHINESE = re.compile(r'[\u4e00-\u9fff]')
RE_JAPANESE = re.compile(r'[\u3040-\u30ff\uff65-\uff9f]')
RE_KOREAN = re.compile(r'[\uac00-\ud7af\u3131-\u318e]')

TARGET_LANG_NAMES = {
    "ko": "한국어 (Korean)",
    "en": "영어 (English)",
    "ja": "일본어 (Japanese)",
    "zh": "중국어 (Chinese)",
    "es": "스페인어 (Spanish)",
}

# 20년 차 시니어 번역가 페르소나 기본 템플릿 ({0}: 원본 언어, {1}: 대상 언어)
SENIOR_TRANSLATOR_PROMPT_TEMPLATE = """당신은 20년 차 이상의 경력을 가진 베테랑 외국어 전문 시니어 번역가입니다.
다음 애니메이션 자막을 {0}에서 자연스럽고 유창한 {1}(으)로 번역해 주세요.
원래의 의미, 감정선, 캐릭터의 성격, 그리고 말투를 그대로 살려주세요. 지나친 직역은 피하고, 장면에 어울리는 자연스러운 대사로 번역해 주세요.
번역 전반에 걸쳐 캐릭터 이름, 용어, 호칭의 일관성을 유지해 주세요.
자막의 줄 순서, 줄바꿈, 서식 태그, 특수 기호는 제공된 그대로 정확하게 유지해 주세요.
설명을 덧붙이거나, 대사를 생략하거나, 분리된 자막을 하나로 합치지 마세요.

[추가 필수 준수 규칙]
1. 이름 번역 금지: 캐릭터 이름이나 인명은 번역하거나 다른 단어로 의역하지 말고 원문 의미/발음 그대로 유지해 주세요(단, 고유명사 사전에 등록된 경우는 사전 표기를 따름).
2. 고유명사 사전 최우선 적용: 함께 제공되는 [고유명사 사전]에 등록된 원문 단어가 대사에 등장할 경우, 반드시 사전에 지정된 '번역 단어'를 그대로 사용해 주세요.
3. 감탄사, 비명, 신음, 숨소리 100% 보존: 등장인물의 감탄사, 비명, 신음, 호흡(예: '앗!', '아아...', '으윽!', '음...', '꺄악!', '하아...')은 삭제하지 말고 1:1로 온전히 살려두세요.
{dictionary_section}
[출력 형식]
반드시 아래 JSON 형식으로만 응답하세요:
{{
  "subtitles": [
    {{"id": 1, "text": "{1} 번역 문장"}}
  ]
}}"""


def detect_source_language_name(segments: List[Dict[str, Any]]) -> str:
    """Infers source language from sample segment texts for dynamic prompt substitution."""
    samples = []
    for s in segments[:40]:
        t = str(s.get("refined_text") or s.get("text") or s.get("raw_text") or "").strip()
        if t:
            samples.append(t)
    joined = " ".join(samples)
    if RE_JAPANESE.search(joined):
        return "일본어"
    elif RE_CHINESE.search(joined):
        return "중국어"
    elif re.search(r'[a-zA-Z]{5,}', joined):
        return "영어"
    return "원문 언어"


def build_dictionary_prompt_section(batch_segments: List[Dict[str, Any]], dict_map: Dict[str, str]) -> str:
    """Builds a formatted [고유명사 사전] section if any registered source words appear in the batch."""
    if not dict_map:
        return ""
    matched: Dict[str, str] = {}
    for s in batch_segments:
        txt = str(s.get("refined_text") or s.get("text") or s.get("raw_text") or "")
        for src, tgt in dict_map.items():
            if src in txt:
                matched[src] = tgt
    if not matched:
        return ""

    lines = ["\n[고유명사 사전 (원문 단어 -> 지정 번역 단어)]"]
    for src, tgt in matched.items():
        lines.append(f"- {src} -> {tgt}")
    return "\n".join(lines)


def apply_dictionary_postprocess(orig_text: str, trans_text: str, dict_map: Dict[str, str]) -> str:
    """
    Ensures that proper nouns registered in the dictionary are accurately reflected
    in the translated subtitle, fixing any untranslated words or dictionary mismatches.
    """
    if not orig_text or not trans_text or not dict_map:
        return trans_text
    res = trans_text
    for src, tgt in dict_map.items():
        if src in orig_text:
            # If the original foreign term was left directly in the translation text
            if src in res:
                res = res.replace(src, tgt)
    return res


def is_foreign_text(text: str) -> bool:
    """Checks if text contains foreign characters (Chinese/Japanese)."""
    if not text:
        return False
    return bool(RE_CHINESE.search(text) or RE_JAPANESE.search(text))


def is_valid_translation_result(original: str, result: str, target_lang: str) -> bool:
    """Validates that translation actually produced clean text in target language."""
    if not result or not str(result).strip():
        return False
    res_str = str(result).strip()
    if target_lang == "ko":
        return is_valid_korean_result(original, res_str)
    return True


def translate_single_segment_fallback(
    seg_id: int,
    original_text: str,
    target_lang: str,
    target_lang_name: str,
    source_lang_name: str = "원문 언어",
    dict_map: Optional[Dict[str, str]] = None
) -> str:
    """Single segment translation fallback with Senior Translator persona and dictionary lookup."""
    if not original_text or not str(original_text).strip():
        return "..."
    orig_clean = str(original_text).strip()
    if target_lang == "ko":
        fast_hit = fast_translate_short(orig_clean)
        if fast_hit:
            if dict_map:
                fast_hit = apply_dictionary_postprocess(orig_clean, fast_hit, dict_map)
            return fast_hit

    dict_map = dict_map or {}
    dict_section = build_dictionary_prompt_section([{"text": orig_clean}], dict_map)

    system_prompt = (
        f"당신은 20년 차 이상의 경력을 가진 베테랑 외국어 전문 시니어 번역가입니다. "
        f"입력된 애니메이션 자막 한 줄을 {source_lang_name}에서 자연스러운 구어체 {target_lang_name}로 번역하여 "
        '반드시 {"text": "번역된 자막"} 형식의 JSON으로만 응답하세요. '
        "이름은 임의로 번역하지 말고 원문 발음/표기를 유지하세요. "
        f"{dict_section}\n"
        "절대로 설명이나 부연 해설을 덧붙이지 마세요."
    )
    user_prompt = json.dumps({"id": seg_id, "text": orig_clean}, ensure_ascii=False)

    for attempt in range(2):
        try:
            content = chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.15 if attempt == 0 else 0.3,
                format_json=True,
                max_tokens=256,
                timeout=45.0
            )
            candidate = ""
            try:
                parsed = json.loads(clean_json_response(content))
                if isinstance(parsed, dict):
                    candidate = str(parsed.get("text") or parsed.get("korean") or parsed.get("translation") or "").strip()
            except Exception:
                candidate = content.strip()

            if target_lang == "ko":
                candidate = sanitize_subtitle_text(orig_clean, candidate)
            if dict_map:
                candidate = apply_dictionary_postprocess(orig_clean, candidate, dict_map)

            if candidate and is_valid_translation_result(orig_clean, candidate, target_lang):
                return candidate
        except Exception as e:
            logger.warning(f"Single segment translation fallback failed for #{seg_id} (attempt {attempt + 1}): {e}")

    fb = fast_translate_short(orig_clean) if target_lang == "ko" else ""
    if fb and dict_map:
        fb = apply_dictionary_postprocess(orig_clean, fb, dict_map)
    return fb or "..."


def translate_batch(
    batch_segments: List[Dict[str, Any]],
    target_lang: str,
    target_lang_name: str,
    source_lang_name: str,
    dict_map: Dict[str, str]
) -> Dict[int, str]:
    """Translates a batch of subtitle segments using the Senior Translator persona & dictionary injection."""
    input_payload = [
        {"id": s.get("index") or s.get("id"), "text": s.get("refined_text") or s.get("text") or s.get("raw_text") or ""}
        for s in batch_segments
    ]

    dict_section = build_dictionary_prompt_section(batch_segments, dict_map)
    system_prompt = SENIOR_TRANSLATOR_PROMPT_TEMPLATE.format(
        source_lang_name,
        target_lang_name,
        dictionary_section=dict_section
    )
    user_prompt = f"다음 애니메이션 자막 세그먼트들을 자연스럽고 유창한 {target_lang_name}로 번역해 주세요:\n{json.dumps(input_payload, ensure_ascii=False)}"

    try:
        response_text = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            format_json=True,
            max_tokens=1500,
            timeout=75.0
        )
    except Exception as e:
        logger.warning(f"Batch chat completion failed: {e}. Falling back to single-segment processing.")
        response_text = ""

    result_map = {}
    if response_text:
        cleaned_json = clean_json_response(response_text)
        if not cleaned_json:
            result_map = extract_subtitles_via_regex(response_text)
        else:
            try:
                parsed = json.loads(cleaned_json)
                result_map = extract_translations_from_parsed(parsed)
            except Exception as e:
                logger.warning(f"Could not parse translation batch JSON ({e}). Falling back to regex.")
                result_map = extract_subtitles_via_regex(response_text)

    # Validation and post-processing pass
    for seg in batch_segments:
        sid = seg.get("index") or seg.get("id")
        orig = seg.get("refined_text") or seg.get("text") or seg.get("raw_text") or ""
        if sid in result_map and result_map[sid]:
            candidate = result_map[sid]
            if target_lang == "ko":
                candidate = sanitize_subtitle_text(orig, candidate)
            # Apply Proper Noun Dictionary replacement
            candidate = apply_dictionary_postprocess(orig, candidate, dict_map)
            if is_valid_translation_result(orig, candidate, target_lang):
                result_map[sid] = candidate
            else:
                logger.info(f"Segment #{sid} invalid translation '{candidate}'. Retrying individually.")
                result_map[sid] = translate_single_segment_fallback(sid, orig, target_lang, target_lang_name, source_lang_name, dict_map)
        else:
            result_map[sid] = translate_single_segment_fallback(sid, orig, target_lang, target_lang_name, source_lang_name, dict_map)

    return result_map


def filter_clean_trans_checkpoint(
    checkpoint: Dict[int, str],
    segments_by_id: Dict[int, Dict[str, Any]],
    target_lang: str,
    dict_map: Dict[str, str]
) -> Dict[int, str]:
    """Sanitizes cached checkpoint items and applies dictionary postprocessing."""
    clean: Dict[int, str] = {}
    for sid, val in checkpoint.items():
        orig_seg = segments_by_id.get(sid)
        orig_text = (orig_seg.get("refined_text") or orig_seg.get("text") or orig_seg.get("raw_text") or "") if orig_seg else ""
        sanitized = sanitize_subtitle_text(orig_text, val) if target_lang == "ko" else val
        sanitized = apply_dictionary_postprocess(orig_text, sanitized, dict_map)
        if is_valid_translation_result(orig_text, sanitized, target_lang):
            clean[sid] = sanitized
        else:
            logger.info(f"Purging invalid/untranslated translation checkpoint #{sid}: '{val}'")
    return clean


def translate_subtitles_list(
    segments: List[Dict[str, Any]],
    target_lang: str = "ko",
    batch_size: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    checkpoint_callback: Optional[Callable[[Dict[int, str]], None]] = None,
    initial_checkpoint: Optional[Dict[int, str]] = None
) -> List[Dict[str, Any]]:
    """
    Translates an entire subtitle list into the target language using
    Senior Translator persona, multi-cloud LLM, and Proper Noun Dictionary.
    """
    if not segments:
        return segments

    if not batch_size:
        batch_size = get_llm_batch_size()

    target_lang_name = TARGET_LANG_NAMES.get(target_lang, target_lang)
    source_lang_name = detect_source_language_name(segments)
    provider = get_active_llm_provider()

    # Load Proper Noun Dictionary
    try:
        dict_map = get_all_dictionary_map()
        logger.info(f"Loaded {len(dict_map)} entries from proper noun dictionary.")
    except Exception as e:
        logger.warning(f"Failed to load dictionary: {e}")
        dict_map = {}

    logger.info(
        f"Starting translation using Provider: [{provider}], "
        f"Source: [{source_lang_name}] -> Target: [{target_lang_name}] ({len(segments)} segments)"
    )

    segments_by_id = {s.get("index") or s.get("id"): s for s in segments}

    checkpoint_map: Dict[int, str] = {}
    if initial_checkpoint:
        checkpoint_map = filter_clean_trans_checkpoint(dict(initial_checkpoint), segments_by_id, target_lang, dict_map)
        logger.info(f"Loaded {len(checkpoint_map)} clean segments from initial checkpoint.")

    total_segments = len(segments)
    total_batches = (total_segments + batch_size - 1) // batch_size
    logger.info(f"Translating {total_segments} segments in {total_batches} batches...")

    translated_segments = [dict(s) for s in segments]

    for i in range(0, total_segments, batch_size):
        batch = translated_segments[i:i + batch_size]
        current_batch_num = (i // batch_size) + 1

        # Check if already cached in clean checkpoint
        all_cached = all(
            (seg.get("index") or seg.get("id")) in checkpoint_map 
            for seg in batch
        )
        if all_cached:
            for seg in batch:
                seg_id = seg.get("index") or seg.get("id")
                seg["original_text"] = seg.get("refined_text") or seg.get("text") or seg.get("raw_text") or ""
                seg["refined_text"] = checkpoint_map[seg_id]
                seg["text"] = checkpoint_map[seg_id]
            if progress_callback:
                progress_callback(current_batch_num, total_batches)
            continue

        try:
            result_map = translate_batch(batch, target_lang, target_lang_name, source_lang_name, dict_map)
            for seg in batch:
                seg_id = seg.get("index") or seg.get("id")
                original = seg.get("refined_text") or seg.get("text") or seg.get("raw_text") or ""
                seg["original_text"] = original
                
                if seg_id in result_map and result_map[seg_id]:
                    trans_text = result_map[seg_id]
                    seg["refined_text"] = trans_text
                    seg["text"] = trans_text
                    if is_valid_translation_result(original, trans_text, target_lang):
                        checkpoint_map[seg_id] = trans_text
                elif seg_id in checkpoint_map:
                    seg["refined_text"] = checkpoint_map[seg_id]
                    seg["text"] = checkpoint_map[seg_id]
                else:
                    fb = translate_single_segment_fallback(seg_id, original, target_lang, target_lang_name, source_lang_name, dict_map)
                    seg["refined_text"] = fb
                    seg["text"] = fb
                    if is_valid_translation_result(original, fb, target_lang):
                        checkpoint_map[seg_id] = fb

            logger.info(f"Translated batch {current_batch_num}/{total_batches}")

            if checkpoint_callback:
                try:
                    checkpoint_callback(checkpoint_map)
                except Exception as cb_err:
                    logger.warning(f"Checkpoint callback failed: {cb_err}")

            if progress_callback:
                progress_callback(current_batch_num, total_batches)

            time.sleep(0.05)
        except Exception as e:
            logger.error(f"Error translating batch {current_batch_num}/{total_batches}: {e}. Retrying individually...")
            for seg in batch:
                seg_id = seg.get("index") or seg.get("id")
                original = seg.get("refined_text") or seg.get("text") or seg.get("raw_text") or ""
                seg["original_text"] = original
                fb = translate_single_segment_fallback(seg_id, original, target_lang, target_lang_name, source_lang_name, dict_map)
                seg["refined_text"] = fb
                seg["text"] = fb
                if is_valid_translation_result(original, fb, target_lang):
                    checkpoint_map[seg_id] = fb
            if progress_callback:
                progress_callback(current_batch_num, total_batches)

    # Final Verification Pass: Ensure ZERO untranslated foreign segments and dictionary accuracy
    untranslated_count = 0
    for seg in translated_segments:
        orig = seg.get("original_text") or seg.get("raw_text") or ""
        cur = seg.get("refined_text") or seg.get("text") or ""
        cur = apply_dictionary_postprocess(orig, cur, dict_map)
        seg["refined_text"] = cur
        seg["text"] = cur

        if not is_valid_translation_result(orig, cur, target_lang):
            untranslated_count += 1
            sid = seg.get("index") or seg.get("id")
            fixed = translate_single_segment_fallback(sid, orig, target_lang, target_lang_name, source_lang_name, dict_map)
            seg["refined_text"] = fixed
            seg["text"] = fixed
            checkpoint_map[sid] = fixed

    if untranslated_count > 0:
        logger.info(f"Completed translation verification pass: corrected {untranslated_count} remaining segments to {target_lang_name}.")
        if checkpoint_callback:
            try:
                checkpoint_callback(checkpoint_map)
            except Exception:
                pass

    return translated_segments
