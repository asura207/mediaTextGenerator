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


def decode_subtitle_bytes(raw_bytes: bytes) -> str:
    """
    Safely decodes .srt subtitle bytes across UTF-8, UTF-8-SIG, UTF-16 (with BOM check),
    CP949/EUC-KR, Shift-JIS (CP932)/EUC-JP, GB18030/Big5, and European encodings.
    Prevents CP949 vs Shift-JIS mojibake collisions by scoring decoded character validity.
    """
    if not raw_bytes:
        return ""

    # 1. Explicit BOM checks first
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        try:
            return raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
    if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw_bytes.decode("utf-16")
        except UnicodeDecodeError:
            pass

    # 2. Strict UTF-8 check
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # 3. Compare CJK regional encodings (CP949/EUC-KR vs Shift-JIS/CP932 vs GB18030) to prevent Mojibake
    cjk_candidates = ("cp949", "euc-kr", "shift_jis", "cp932", "euc-jp", "gb18030", "big5")
    best_cjk_text = None
    best_cjk_score = -1.0

    for enc in cjk_candidates:
        try:
            decoded = raw_bytes.decode(enc)
            if "-->" not in decoded:
                continue
            # Count common natural characters vs rare mojibake symbols
            common_ko = len(re.findall(r"[\uac00-\ud7a3]", decoded))
            common_ja = len(re.findall(r"[\u3040-\u309f\u30a0-\u30ff]", decoded))
            common_han = len(re.findall(r"[\u4e00-\u9fff]", decoded))
            total_cjk = max(1, common_ko + common_ja + common_han)
            if enc in ("shift_jis", "cp932", "euc-jp"):
                score = (common_ja * 2.5 + common_han) / total_cjk if common_ja > 0 else 0.1
            elif enc in ("cp949", "euc-kr"):
                # Genuine Korean text has high syllable density and almost no kana
                score = (common_ko * 2.0) / total_cjk if common_ko > 0 and common_ja == 0 else 0.2
            else:
                score = (common_han * 1.5) / total_cjk if common_ja == 0 and common_ko == 0 else 0.1

            if score > best_cjk_score:
                best_cjk_score = score
                best_cjk_text = decoded
        except (UnicodeDecodeError, LookupError):
            continue

    if best_cjk_text is not None:
        return best_cjk_text

    # 4. Single-byte European / Cyrillic / Arabic / Thai fallback encodings
    for enc in ("cp1251", "cp1256", "cp874", "cp1254", "cp1252", "latin-1"):
        try:
            decoded = raw_bytes.decode(enc)
            if "-->" in decoded:
                return decoded
        except (UnicodeDecodeError, LookupError):
            continue

    return raw_bytes.decode("utf-8", errors="replace")


def _detect_script_language(text: str) -> Dict[str, Any] | None:
    """
    Fast Unicode-script check for non-Latin and mixed-language subtitles before statistical langdetect.
    In mixed-language subtitles (e.g., Korean + English/Japanese), prioritizes the dominant foreign script
    unless Hangul is clearly the majority (>= 60%).
    """
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

    # Only classify as Korean ('ko') if Hangul is genuinely the majority script (>= 60%)
    if (hangul / total) >= 0.60 and hiragana_katakana == 0:
        return {"code": "ko", "name": LANG_NAMES["ko"], "confidence": round(hangul / total, 2)}
    if hiragana_katakana > 0 and ((hiragana_katakana + cjk) / total) >= 0.15:
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

    # If mixed Hangul + Latin where Latin is < 40% and Hangul is still the single largest script
    if hangul > 0 and hangul >= latin and (hangul / total) >= 0.35:
        return {"code": "ko", "name": LANG_NAMES["ko"], "confidence": round(hangul / total, 2)}
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

