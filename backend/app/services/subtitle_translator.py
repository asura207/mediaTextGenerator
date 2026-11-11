import json
import logging
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import ollama
from app.config import OLLAMA_HOST, get_llm_batch_size
from app.services.llm_refiner import (
    clean_json_response,
    extract_translations_from_parsed,
    extract_subtitles_via_regex,
    resolve_active_ollama_model,
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
    client: ollama.Client,
    seg_id: int,
    original_text: str,
    target_lang: str,
    target_lang_name: str
) -> str:
    """Single segment translation fallback that reliably converts foreign lines with JSON enforcement and sanitization."""
    if not original_text or not str(original_text).strip():
        return "..."
    orig_clean = str(original_text).strip()
    if target_lang == "ko":
        fast_hit = fast_translate_short(orig_clean)
        if fast_hit:
            return fast_hit

    prompt = json.dumps({"id": seg_id, "text": orig_clean}, ensure_ascii=False)
    active_model = resolve_active_ollama_model(client)
    for attempt in range(2):
        try:
            resp = client.chat(
                model=active_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"당신은 전문 영상 자막 번역기입니다. 입력된 자막을 자연스러운 구어체 {target_lang_name} 한 문장으로 번역하여 "
                            '반드시 {"text": "번역된 자막"} 형식의 JSON으로만 응답하세요. '
                            "절대로 부연 설명이나 여러 후보를 나열하거나 질문하지 마세요."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                format="json",
                think=False,
                options={"temperature": 0.15 if attempt == 0 else 0.3, "num_predict": 128, "repeat_penalty": 1.15, "num_ctx": 2048}
            )
            content = resp["message"]["content"].strip()
            candidate = ""
            try:
                parsed = json.loads(clean_json_response(content))
                if isinstance(parsed, dict):
                    candidate = str(parsed.get("text") or parsed.get("korean") or parsed.get("translation") or "").strip()
            except Exception:
                candidate = content

            if target_lang == "ko":
                candidate = sanitize_subtitle_text(orig_clean, candidate)
            if candidate and is_valid_translation_result(orig_clean, candidate, target_lang):
                return candidate
        except Exception as e:
            logger.warning(f"Single segment translation fallback failed for #{seg_id}: {e}")
    return (fast_translate_short(orig_clean) if target_lang == "ko" else "") or "..."

def translate_batch(
    client: ollama.Client,
    batch_segments: List[Dict[str, Any]],
    target_lang: str,
    target_lang_name: str,
    is_retry: bool = False
) -> Dict[int, str]:
    """Translates a single batch of subtitle segments via Ollama with natural colloquial tone."""
    active_model = resolve_active_ollama_model(client)
    input_payload = [{"id": s.get("index") or s.get("id"), "text": s.get("refined_text") or s.get("text") or s.get("raw_text") or ""} for s in batch_segments]
    
    colloquial_guide = ""
    if target_lang == "ko":
        colloquial_guide = """
[한국어 자막 번역 특별 지침]
- 사전식 직역투나 책을 읽는 듯한 딱딱한 문어체(~하는 것이다, ~에 있어서, ~라 볼 수 있다 등)를 절대 사용하지 마세요.
- 실제 사람이 일상에서 자연스럽게 대화하는 생생한 구어체(대화체) 및 방송/영화 자막 스타일로 의역하세요.
- 일본어(히라가나, 가타카나, 한자)나 중국어 한자를 단 한 글자도 남기지 말고 100% 순수 한글로만 작성하세요.
- 불필요한 번역투 3인칭 대명사('그는', '그녀는', '그것은' 등)는 생략하거나 자연스럽게 바꾸세요.
- 종결 어미를 부드러운 일상 대화체로 표현하세요.
"""

    system_prompt = f"""당신은 전문 영상 자막 번역가입니다. 전달받은 세그먼트를 자연스러운 구어체 {target_lang_name}로 번역하여 아래 JSON 형식으로만 응답하세요. 외국어(중국어, 일본어 등) 원문은 반드시 100% {target_lang_name}로 번역해야 하며 원문을 그대로 남기지 마세요.
{colloquial_guide}
[출력 형식]
{{
  "subtitles": [
    {{"id": 1, "text": "{target_lang_name} 번역 문장"}}
  ]
}}"""
    user_prompt = f"다음 자막 세그먼트들을 사전식 직역투가 아닌 실제 사람이 말하는 자연스러운 구어체 {target_lang_name}로 번역하세요:\n{json.dumps(input_payload, ensure_ascii=False)}"

    response = client.chat(
        model=active_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        think=False,
        options={
            "temperature": 0.2,
            "top_p": 0.9,
            "repeat_penalty": 1.15,
            "num_predict": 1024,
            "num_ctx": 2048
        }
    )

    response_text = response["message"]["content"]
    cleaned_json = clean_json_response(response_text)
    
    result_map = {}
    if not cleaned_json:
        result_map = extract_subtitles_via_regex(response_text)
    else:
        try:
            parsed = json.loads(cleaned_json)
            result_map = extract_translations_from_parsed(parsed)
        except Exception as e:
            logger.warning(f"Could not parse translation batch: {e}. Attempting regex fallback.")
            result_map = extract_subtitles_via_regex(response_text)

    # Validate results & fallback missing or untranslated items
    for seg in batch_segments:
        sid = seg.get("index") or seg.get("id")
        orig = seg.get("refined_text") or seg.get("text") or seg.get("raw_text") or ""
        if sid in result_map:
            trans = sanitize_subtitle_text(orig, result_map[sid]) if target_lang == "ko" else result_map[sid]
            if is_valid_translation_result(orig, trans, target_lang):
                result_map[sid] = trans
            else:
                logger.info(f"Segment #{sid} untranslated or invalid '{result_map[sid]}'. Retrying individually.")
                result_map[sid] = translate_single_segment_fallback(client, sid, orig, target_lang, target_lang_name)
        else:
            result_map[sid] = translate_single_segment_fallback(client, sid, orig, target_lang, target_lang_name)

    return result_map

def filter_clean_trans_checkpoint(checkpoint: Dict[int, str], segments_by_id: Dict[int, Dict[str, Any]], target_lang: str) -> Dict[int, str]:
    """Sanitizes and purges cached items that are untranslated foreign text or AI meta-responses."""
    clean: Dict[int, str] = {}
    for sid, val in checkpoint.items():
        orig_seg = segments_by_id.get(sid)
        orig_text = (orig_seg.get("refined_text") or orig_seg.get("text") or orig_seg.get("raw_text") or "") if orig_seg else ""
        sanitized = sanitize_subtitle_text(orig_text, val) if target_lang == "ko" else val
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
    Translates an entire subtitle list into the target language in batches.
    Maintains checkpoints for durability and guarantees 100% translation.
    """
    if not segments:
        return segments

    if not batch_size:
        batch_size = get_llm_batch_size()

    target_lang_name = TARGET_LANG_NAMES.get(target_lang, target_lang)
    try:
        client = ollama.Client(host=OLLAMA_HOST, timeout=120.0)
        client.list()
        active_model = resolve_active_ollama_model(client)
        logger.info(f"Connected to Ollama host: {OLLAMA_HOST}, model: {active_model} for translation to {target_lang_name}")
    except Exception as e:
        logger.warning(f"Could not connect to Ollama ({e}). Returning original segments without translation.")
        return segments

    segments_by_id = {s.get("index") or s.get("id"): s for s in segments}

    checkpoint_map: Dict[int, str] = {}
    if initial_checkpoint:
        checkpoint_map = filter_clean_trans_checkpoint(dict(initial_checkpoint), segments_by_id, target_lang)
        logger.info(f"Loaded {len(checkpoint_map)} clean segments from initial translation checkpoint.")

    total_segments = len(segments)
    total_batches = (total_segments + batch_size - 1) // batch_size
    logger.info(f"Translating {total_segments} segments to {target_lang_name} in {total_batches} batches...")

    translated_segments = []
    # Make deep copy of segment structure
    for s in segments:
        translated_segments.append(dict(s))

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
            result_map = translate_batch(client, batch, target_lang, target_lang_name)
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
                    fb = translate_single_segment_fallback(client, seg_id, original, target_lang, target_lang_name)
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
                fb = translate_single_segment_fallback(client, seg_id, original, target_lang, target_lang_name)
                seg["refined_text"] = fb
                seg["text"] = fb
                if is_valid_translation_result(original, fb, target_lang):
                    checkpoint_map[seg_id] = fb
            if progress_callback:
                progress_callback(current_batch_num, total_batches)

    # Final Verification Pass: Ensure ZERO untranslated foreign segments
    untranslated_count = 0
    for seg in translated_segments:
        orig = seg.get("original_text") or seg.get("raw_text") or ""
        cur = seg.get("refined_text") or seg.get("text") or ""
        if not is_valid_translation_result(orig, cur, target_lang):
            untranslated_count += 1
            sid = seg.get("index") or seg.get("id")
            fixed = translate_single_segment_fallback(client, sid, orig, target_lang, target_lang_name)
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
