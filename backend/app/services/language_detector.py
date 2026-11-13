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
    "it": "이탈리아어 (Italian)",
    "pt": "포르투갈어 (Portuguese)",
    "nl": "네덜란드어 (Dutch)",
    "pl": "폴란드어 (Polish)",
    "uk": "우크라이나어 (Ukrainian)",
    "cs": "체코어 (Czech)",
    "ro": "루마니아어 (Romanian)",
    "hu": "헝가리어 (Hungarian)",
    "sv": "스웨덴어 (Swedish)",
    "no": "노르웨이어 (Norwegian)",
    "da": "덴마크어 (Danish)",
    "fi": "핀란드어 (Finnish)",
    "el": "그리스어 (Greek)",
    "tr": "튀르키예어 (Turkish)",
    "ar": "아랍어 (Arabic)",
    "he": "히브리어 (Hebrew)",
    "fa": "페르시아어 (Persian)",
    "hi": "힌디어 (Hindi)",
    "bn": "벵골어 (Bengali)",
    "ta": "타밀어 (Tamil)",
    "te": "텔루구어 (Telugu)",
    "th": "태국어 (Thai)",
    "vi": "베트남어 (Vietnamese)",
    "id": "인도네시아어 (Indonesian)",
    "ms": "말레이어 (Malay)",
    "tl": "타갈로그어 (Tagalog)",
    "sw": "스와힐리어 (Swahili)",
    "unknown": "알 수 없음 (Unknown)",
}

RE_HTML_OR_ASS_TAG = re.compile(r'<[^>]+>|\{\\[^}]+\}')


def _detect_script_language(text: str) -> Dict[str, Any] | None:
    """Fast Unicode-script check for non-Latin scripts before statistical langdetect."""
    hangul = len(re.findall(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]', text))
    hiragana_katakana = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text))
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    latin = len(re.findall(r'[a-zA-Z\u00c0-\u024f]', text))
    cyrillic = len(re.findall(r'[\u0400-\u04ff]', text))
    arabic = len(re.findall(r'[\u0600-\u06ff]', text))
    thai = len(re.findall(r'[\u0e00-\u0e7f]', text))
    devanagari = len(re.findall(r'[\u0900-\u097f]', text))
    greek = len(re.findall(r'[\u0370-\u03ff]', text))
    hebrew = len(re.findall(r'[\u0590-\u05ff]', text))

    total = hangul + hiragana_katakana + cjk + latin + cyrillic + arabic + thai + devanagari + greek + hebrew
    if total == 0:
        return None

    if (hangul / total) > 0.15:
        return {"code": "ko", "name": LANG_NAMES["ko"], "confidence": round(hangul / total, 2)}
    if hiragana_katakana > 0:
        return {"code": "ja", "name": LANG_NAMES["ja"], "confidence": round((hiragana_katakana + cjk) / total, 2)}
    if (cjk / total) > 0.25:
        return {"code": "zh", "name": LANG_NAMES["zh"], "confidence": round(cjk / total, 2)}
    if (thai / total) > 0.25:
        return {"code": "th", "name": LANG_NAMES["th"], "confidence": round(thai / total, 2)}
    if (arabic / total) > 0.25:
        return {"code": "ar", "name": LANG_NAMES["ar"], "confidence": round(arabic / total, 2)}
    if (devanagari / total) > 0.25:
        return {"code": "hi", "name": LANG_NAMES["hi"], "confidence": round(devanagari / total, 2)}
    if (greek / total) > 0.25:
        return {"code": "el", "name": LANG_NAMES["el"], "confidence": round(greek / total, 2)}
    if (hebrew / total) > 0.25:
        return {"code": "he", "name": LANG_NAMES["he"], "confidence": round(hebrew / total, 2)}
    if (cyrillic / total) > 0.25 and cyrillic < 20:
        return {"code": "ru", "name": LANG_NAMES["ru"], "confidence": round(cyrillic / total, 2)}
    return None


def detect_text_language(text: str) -> Dict[str, Any]:
    """
    Detects language of given text sample across all world scripts and ISO-639 languages
    using Unicode script frequency analysis combined with langdetect.
    """
    if not text or not text.strip():
        return {"code": "unknown", "name": LANG_NAMES["unknown"], "confidence": 0.0}

    cleaned = RE_HTML_OR_ASS_TAG.sub(" ", text).strip()
    if not cleaned:
        return {"code": "unknown", "name": LANG_NAMES["unknown"], "confidence": 0.0}

    script_hit = _detect_script_language(cleaned)
    if script_hit:
        return script_hit

    # Fallback to langdetect across all supported languages (European, Cyrillic, Vietnamese, Indonesian, etc.)
    try:
        langs = detect_langs(cleaned)
        if langs:
            top = langs[0]
            code = top.lang.split("-")[0] if "-" in top.lang else top.lang
            if code.startswith("zh"):
                code = "zh"
            name = LANG_NAMES.get(code, f"기타 언어 ({code})")
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

