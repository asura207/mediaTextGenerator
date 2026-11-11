import re
import logging
from typing import Dict, Any, List
from langdetect import detect_langs

logger = logging.getLogger(__name__)

LANG_NAMES = {
    "ko": "한국어 (Korean)",
    "zh": "중국어 (Chinese)",
    "ja": "일본어 (Japanese)",
    "en": "영어 (English)",
    "ru": "러시아어 (Russian)",
    "es": "스페인어 (Spanish)",
    "fr": "프랑스어 (French)",
    "de": "독일어 (German)",
    "unknown": "알 수 없음 (Unknown)",
}

def detect_text_language(text: str) -> Dict[str, Any]:
    """
    Detects language of given text sample using high-precision character set 
    frequency analysis (essential for CJK) combined with langdetect.
    """
    if not text or not text.strip():
        return {"code": "unknown", "name": LANG_NAMES["unknown"], "confidence": 0.0}

    hangul = len(re.findall(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]', text))
    hiragana_katakana = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text))
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    latin = len(re.findall(r'[a-zA-Z]', text))
    cyrillic = len(re.findall(r'[\u0400-\u04ff]', text))

    total = hangul + hiragana_katakana + cjk + latin + cyrillic
    if total > 0:
        if (hangul / total) > 0.15:
            return {"code": "ko", "name": LANG_NAMES["ko"], "confidence": round(hangul / total, 2)}
        if hiragana_katakana > 0:
            return {"code": "ja", "name": LANG_NAMES["ja"], "confidence": round((hiragana_katakana + cjk) / total, 2)}
        if (cjk / total) > 0.25:
            return {"code": "zh", "name": LANG_NAMES["zh"], "confidence": round(cjk / total, 2)}
        if (cyrillic / total) > 0.25:
            return {"code": "ru", "name": LANG_NAMES["ru"], "confidence": round(cyrillic / total, 2)}

    # Fallback to langdetect
    try:
        langs = detect_langs(text)
        if langs:
            top = langs[0]
            code = top.lang
            if code.startswith("zh"):
                code = "zh"
            name = LANG_NAMES.get(code, f"기타 ({code})")
            return {"code": code, "name": name, "confidence": round(top.prob, 2)}
    except Exception as e:
        logger.warning(f"langdetect failed: {e}")

    return {"code": "unknown", "name": LANG_NAMES["unknown"], "confidence": 0.0}

def detect_subtitles_language(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Detects primary language from a list of subtitle segments."""
    sample_texts = []
    for s in segments[:100]:
        t = s.get("refined_text") or s.get("raw_text") or s.get("text") or ""
        if t.strip():
            sample_texts.append(t.strip())
            
    combined = " ".join(sample_texts)
    return detect_text_language(combined)

