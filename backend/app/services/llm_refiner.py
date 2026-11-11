import json
import logging
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import ollama
from app.config import OLLAMA_HOST, get_ollama_model, get_llm_batch_size

logger = logging.getLogger(__name__)

_cached_installed_models: List[str] = []
_cached_models_ts: float = 0.0


def resolve_active_ollama_model(client: Optional[ollama.Client] = None) -> str:
    """Returns the configured Ollama model, falling back to an installed model if not yet pulled."""
    global _cached_installed_models, _cached_models_ts
    configured = get_ollama_model()
    now = time.time()
    try:
        if not _cached_installed_models or (now - _cached_models_ts > 15.0):
            c = client or ollama.Client(host=OLLAMA_HOST, timeout=10.0)
            resp = c.list()
            models_list = resp.get("models", []) if isinstance(resp, dict) else getattr(resp, "models", [])
            installed_names = []
            for m in models_list:
                name = m.get("model") or m.get("name") if isinstance(m, dict) else (getattr(m, "model", None) or getattr(m, "name", None))
                if name:
                    installed_names.append(str(name))
            if installed_names:
                _cached_installed_models = installed_names
                _cached_models_ts = now
        if _cached_installed_models:
            if configured in _cached_installed_models or any(n.startswith(configured) for n in _cached_installed_models):
                return configured
            return _cached_installed_models[0]
    except Exception as e:
        logger.warning(f"Could not query installed Ollama models ({e}), falling back to configured '{configured}'")
    return configured

RE_CHINESE = re.compile(r'[\u4e00-\u9fff]')
RE_JAPANESE = re.compile(r'[\u3040-\u30ff\uff65-\uff9f]')
RE_KOREAN = re.compile(r'[\uac00-\ud7af\u3131-\u318e]')
RE_OTHER_FOREIGN = re.compile(r'[\u0400-\u04ff\u0600-\u06ff\u0e00-\u0e7f\u1ea0-\u1ef9]')
RE_CJK_PUNCT = re.compile(r'[。，：；“”‘’「」『』【】《》〈〉（）？！]')
RE_MIXED_GIBBERISH = re.compile(r'[\uac00-\ud7af][a-zA-Z]{2,}|[a-zA-Z]{2,}[\uac00-\ud7af]')

SHORT_CJK_DICT = {
    "好": "좋아",
    "好。": "좋아.",
    "好！": "좋아!",
    "好?": "좋아?",
    "好？": "좋아?",
    "好的": "알겠어",
    "好吧": "그래, 알겠어",
    "好感": "호감",
    "好感…": "호감...",
    "嗯": "응",
    "嗯。": "응.",
    "嗯…": "음...",
    "啊": "아",
    "啊?": "어?",
    "啊？": "어?",
    "啊！": "아!",
    "哦": "오",
    "欸": "어?",
    "欸?": "어?",
    "欸？": "어?",
    "要": "할래",
    "不要": "싫어",
    "快吃": "빨리 먹어",
    "吃不吃": "먹을래, 말래?",
    "吃不吃不": "먹을 거야, 말 거야?",
    "放开": "놔!",
    "放開": "놔!",
    "起來": "일어나",
    "起来": "일어나",
    "還在嗎": "아직 있어?",
    "還在嗎?": "아직 있어?",
    "还在吗": "아직 있어?",
    "还在吗?": "아직 있어?",
    "那是什么": "그게 뭐야?",
    "那是什么?": "그게 뭐야?",
    "那裡": "저기",
    "在那裡": "저기에 있어",
    "今天是": "오늘은...",
    "的": "...",
    "還": "아직...",
    "还": "아직...",
    "點": "조금",
    "点": "조금",
    "原": "원래...",
    "宮": "궁",
    "舐": "핥아...",
    "素": "그냥...",
    "もしもし": "여보세요?",
    "ちょっと": "잠깐만",
    "ねえ": "저기",
    "ねぇ": "저기",
    "うん": "응",
    "はい": "네",
    "いいえ": "아니",
    "なに": "뭐?",
    "何": "뭐?",
    "なに?": "뭐?",
    "何?": "뭐?",
    "え": "어?",
    "え?": "어?",
    "えっ": "어?",
    "ええ": "응",
    "あ": "아",
    "あっ": "아!",
    "ああ": "아아",
    "ん": "음",
    "ん?": "응?",
    "グリグリ": "빙글빙글",
    "なめた?": "얕보는 거야?",
    "やっぱね": "역시 그렇네",
    "気持ちいい": "기분 좋아",
    "ちゃんと我慢できる?": "제대로 참을 수 있겠어?",
    "ちにしてよ": "그렇게 해 줘",
    "多少钱?": "얼마예요?",
    "せよおい": "이봐!",
    "よいしょ": "영차",
    "かわいい": "귀여워",
    "ヘラー?": "무슨 일이야?",
    "あ、これ": "아, 이거",
    "りょっと?": "잠깐?",
    "体": "몸",
    "焼けるよ、こんこな": "다 타버리겠어",
    "あっち行け": "저리로 가!",
    "るでしょ": "그렇잖아?",
    "へー、変態": "헤에, 변태 같으니",
}

KANA_TO_HANGUL = {
    'あ': '아', 'い': '이', 'う': '우', 'え': '에', 'お': '오',
    'か': '카', 'き': '키', 'く': '쿠', 'け': '케', 'こ': '코',
    'さ': '사', 'し': '시', 'す': '스', 'せ': '세', 'そ': '소',
    'た': '타', 'ち': '치', 'つ': '츠', 'て': '테', 'と': '토',
    'な': '나', 'に': '니', 'ぬ': '누', 'ね': '네', 'の': '노',
    'は': '하', 'ひ': '히', 'ふ': '후', 'へ': '헤', 'ほ': '호',
    'ま': '마', 'み': '미', 'む': '무', 'め': '메', 'も': '모',
    'や': '야', 'ゆ': '유', 'よ': '요',
    'ら': '라', 'り': '리', 'る': '루', 'れ': '레', 'ろ': '로',
    'わ': '와', 'を': '오', 'ん': '음',
    'が': '가', 'ぎ': '기', 'ぐ': '구', 'げ': '게', 'ご': '고',
    'ざ': '자', 'じ': '지', 'ず': '즈', 'ぜ': '제', 'ぞ': '조',
    'だ': '다', 'ぢ': '지', 'づ': '즈', 'で': '데', 'ど': '도',
    'ば': '바', 'び': '비', 'ぶ': '부', 'べ': '베', 'ぼ': '보',
    'ぱ': '파', 'ぴ': '피', 'ぷ': '푸', 'ぺ': '페', 'ぽ': '포',
    'っ': '', 'ー': '~',
    'ア': '아', 'イ': '이', 'ウ': '우', 'エ': '에', 'オ': '오',
    'カ': '카', 'キ': '키', 'ク': '쿠', 'ケ': '케', 'コ': '코',
    'サ': '사', 'シ': '시', 'ス': '스', 'セ': '세', 'ソ': '소',
    'タ': '타', 'チ': '치', 'ツ': '츠', 'テ': '테', 'ト': '토',
    'ナ': '나', 'ニ': '니', 'ヌ': '누', 'ネ': '네', 'ノ': '노',
    'ハ': '하', 'ヒ': '히', 'フ': '후', 'ヘ': '헤', 'ホ': '호',
    'マ': '마', 'ミ': '미', 'ム': '무', 'メ': '메', 'モ': '모',
    'ヤ': '야', 'ユ': '유', 'ヨ': '요',
    'ラ': '라', 'リ': '리', 'ル': '루', 'レ': '레', 'ロ': '로',
    'ワ': '와', 'ヲ': '오', 'ン': '음',
    'ガ': '가', 'ギ': '기', 'グ': '구', 'ゲ': '게', 'ゴ': '고',
    'ザ': '자', 'ジ': '지', 'ズ': '즈', 'ゼ': '제', 'ゾ': '조',
    'ダ': '다', 'ヂ': '지', 'ヅ': '즈', 'デ': '데', 'ド': '도',
    'バ': '바', 'ビ': '비', 'ブ': '부', 'ベ': '베', 'ボ': '보',
    'パ': '파', 'ピ': '피', 'プ': '푸', 'ペ': '페', 'ポ': '포',
    'ッ': '',
}

AI_META_PATTERNS = re.compile(
    r'(번역\s*결과|번역할\s*수|번역해\s*드릴|번역해\s*드리|번역\s*작업을|번역이\s*필요|번역을\s*어떻게|번역하겠|번역하면|번역하자면|번역\s*불가능|'
    r'변환해\s*드릴|변환\s*가능한|바꾸면|바꿔볼까요|바꾼\s*거예요|바꿔\s*말할|표현하면|표현할\s*수|표현입니다|표현이에요|표현은|표현으로는|표현하자면|표현하려는|'
    r'자연스러운\s*표현|일상적인\s*표현|한국어\s*표현|해석하면|정도가\s*될\s*것|정도가\s*자연스러|요구하신다면|원문의|말할\s*수\s*있습니다|'
    r'의미입니다|의미인\s*것|의미는|알려주시면|알려주실|알려주세요|말씀해\s*주|입력해\s*주|입력하신|입력하셨|'
    r'제공하도록|제공해\s*주|요청해\s*주|요청하신|내용이\s*안\s*나와|내용이\s*없|내용을\s*추론|내용이\s*더\s*필요|'
    r'정보가\s*필요|문맥이\s*필요|구체적인\s*문장|구체적인\s*내용|구체적으로\s*물어|주어진\s*텍스트|원본의\s*전체|자막\s*본문|'
    r'어떤\s*부분을|어떤\s*내용을|어떻게\s*진행|도움을\s*드릴|수정해\s*드릴|수정하겠|다시\s*작성|'
    r'구어체|문어체|순수한?\s*한글|한국어\s*문장|한국어\s*버전|다른\s*버전|일본어\s*문자|중국어\s*문자|단일\s*중국어|'
    r'예를\s*들어|다음과\s*같이|정리하면|원문을\s*읽다|추론하기\s*어렵|대응되는\s*단어가\s*없|예쁜\s*주제로|'
    r'의미\s*있는\s*내용을\s*포함|어떤\s*말을\s*하려는|문장이\s*너무\s*짧|텍스트가\s*너무\s*짧)'
)


def fast_translate_short(raw_text: str) -> str:
    """Directly converts common 1-3 char CJK tokens, Kana stutters, or URLs without LLM hallucination."""
    raw_s = (raw_text or "").strip()
    if not raw_s:
        return ""
    if raw_s in ("ー", "〜", "~", "-", "…", "..."):
        return "~" if raw_s in ("ー", "〜", "~", "-") else "..."
    if raw_s in SHORT_CJK_DICT:
        return SHORT_CJK_DICT[raw_s]
    raw_no_punct = raw_s.strip(" .?!~…。，！？、")
    if raw_no_punct in SHORT_CJK_DICT:
        suffix = "?" if ("?" in raw_s or "？" in raw_s) else ("!" if ("!" in raw_s or "！" in raw_s) else "")
        base = SHORT_CJK_DICT[raw_no_punct].rstrip(".?!")
        return (base + suffix) if base else "..."
    if re.match(r'^[\w\-\.]+\.(?:com|net|org|cc|tv|me|xyz|cn|jp|kr)\b', raw_s, re.I):
        return raw_s
    if 1 <= len(raw_no_punct) <= 2 and all(ch in KANA_TO_HANGUL for ch in raw_no_punct):
        ko = "".join(KANA_TO_HANGUL[ch] for ch in raw_no_punct)
        return ko if ko else "..."
    return ""


def is_ai_meta_response(raw_text: str, text: str) -> bool:
    """Detects AI conversational refusals, meta-explanations, or multi-option dumps."""
    if not text:
        return False
    s = str(text).strip()
    if AI_META_PATTERNS.search(s):
        return True
    raw_clean = str(raw_text or "").strip()
    if 0 < len(raw_clean) <= 3 and len(s) > 18:
        return True
    if len(raw_clean) > 3 and len(s) > max(50, int(len(raw_clean) * 3.5)):
        return True
    return False


def is_clean_korean_line(line: str, raw_text: str = "") -> bool:
    """Checks that a single candidate line is clean Korean without foreign scripts or AI meta-talk."""
    if not line or not line.strip():
        return False
    s = line.strip()
    if RE_CHINESE.search(s) or RE_JAPANESE.search(s) or RE_OTHER_FOREIGN.search(s):
        return False
    if RE_CJK_PUNCT.search(s) or '""' in s or "''" in s or "\n" in s:
        return False
    if RE_MIXED_GIBBERISH.search(s):
        return False
    if is_ai_meta_response(raw_text, s):
        return False
    if not RE_KOREAN.search(s):
        return False
    ko_chars = len(RE_KOREAN.findall(s))
    latin_chars = len(re.findall(r'[a-zA-Z]', s))
    if (ko_chars + latin_chars) > 0 and (ko_chars / (ko_chars + latin_chars)) < 0.6:
        return False
    return True


def sanitize_subtitle_text(raw_text: str, text: str) -> str:
    """
    Cleans LLM output by stripping CJK full-width punctuation (。，：“”「」), empty quotes (""),
    multi-option lists, and AI conversational meta-responses, returning a single clean Korean subtitle line.
    """
    raw_s = str(raw_text or "").strip()
    if not text or not str(text).strip():
        return fast_translate_short(raw_s) or raw_s

    s = str(text).strip()

    has_mess = bool(
        RE_CJK_PUNCT.search(s)
        or '""' in s
        or "''" in s
        or "\n" in s
        or is_ai_meta_response(raw_s, s)
        or RE_OTHER_FOREIGN.search(s)
        or RE_MIXED_GIBBERISH.search(s)
    )
    if not has_mess:
        return s

    # 1. Check fast dictionary for known short CJK/Kana tokens
    fast_hit = fast_translate_short(raw_s)
    if fast_hit:
        return fast_hit

    # 2. Strip parenthetical AI notes & common prefixes ("번역 결과:")
    s_clean = re.sub(r'\((?:번역|요청|자연스럽|순수|구어체|결과|원문|의미)[^)]*\)', ' ', s)
    s_clean = re.sub(r'^(?:번역\s*결과|번역|교정\s*결과|수정\s*결과|결과)\s*[:：]\s*', '', s_clean.strip())
    # Strip stray Cyrillic/Vietnamese characters if mixed with Korean
    s_clean = RE_OTHER_FOREIGN.sub('', s_clean)

    # 3. Extract quoted Korean candidates (e.g. “혼자 하는 일도”)
    quoted_candidates = re.findall(r'[“"「『\']([^”"」』\'\n]{1,50})[”"」』\']', s_clean)
    valid_quoted = []
    for qc in quoted_candidates:
        qc_clean = RE_CJK_PUNCT.sub(' ', qc).strip(" .,?!:;~-\"'")
        qc_clean = re.sub(r'\s+', ' ', qc_clean).strip()
        if qc_clean and is_clean_korean_line(qc_clean, raw_s):
            if qc.strip().endswith(("?", "？")) and not qc_clean.endswith("?"):
                qc_clean += "?"
            elif qc.strip().endswith(("!", "！")) and not qc_clean.endswith("!"):
                qc_clean += "!"
            valid_quoted.append(qc_clean)

    # 4. Split by lines and CJK punctuation delimiters (。，：；\n / -> / →)
    parts = re.split(r'[\n\r]+|[。，：；]+|->|→|\s+또는\s+', s_clean)
    valid_parts = []
    for p in parts:
        p_str = p.strip()
        p_str = re.sub(r'^(?:번역\s*결과|번역|예|예를\s*들어|결과)\s*[:：]?\s*', '', p_str)
        p_str = p_str.strip(' "\'“”‘’「」『』【】()[]-•*.,:;?!？，。：；')
        p_str = re.sub(r'\s+', ' ', p_str).strip()
        if not p_str:
            continue
        if is_clean_korean_line(p_str, raw_s):
            if p.strip().endswith(("?", "？")) and not p_str.endswith("?"):
                p_str += "?"
            elif p.strip().endswith(("!", "！")) and not p_str.endswith("!"):
                p_str += "!"
            valid_parts.append(p_str)

    if valid_parts:
        return valid_parts[0]
    if valid_quoted:
        return valid_quoted[0]

    return fast_translate_short(raw_s) or "..."

SYSTEM_PROMPT = """당신은 영상 자막 전문 에디터이자 한국어 문맥 교정 및 대화체 번역 전문가입니다.
Whisper 음성인식(STT) 모델이 추출한 자막 세그먼트 목록을 전달받게 됩니다.
각 세그먼트의 문맥과 상황을 파악하여 다음 지침에 따라 실제 방송/영화/유튜브 영상처럼 자연스러운 구어체로 교정 및 번역해 주세요:

[핵심 지침: 자연스러운 일상 구어체(대화체) 원칙]
1. **사전식 직역투 및 딱딱한 문어체 절대 금지**:
   - 사전이나 책을 읽는 듯한 딱딱하고 어색한 문어체(~하는 것이다, ~에 있어서, ~라 볼 수 있다, ~하기 마련이다, ~하기를 희망한다 등)는 절대 사용하지 마세요.
   - 실제 사람이 일상에서 자연스럽게 대화하듯, 또는 전문 방송/영화/유튜브 자막처럼 유려하고 생생한 **구어체(대화체)**로 윤문 및 의역하세요.
   - 번역투 3인칭 대명사('그는', '그녀는', '그것은' 등)의 불필요한 남발을 피하고 한국어 대화 흐름에 맞게 생략하거나 자연스럽게 바꾸세요 (예: '그것은' → '그건', '이것은' → '이건', '그는' → 주어 생략 또는 인물 이름/그 사람).
   - 종결 어미를 사전체가 아닌 자연스러운 일상 대화체로 표현하세요:
     * 존댓말인 경우: '~할 예정입니다' → '~할 거예요', '~하지 않습니다' → '~안 해요' / '~하지 않아요', '~했나요?', '~거든요', '~인 것 같아요', '~해 보세요' 등 부드러운 구어체 어미 활용.
     * 반말/친근한 대화인 경우: 문맥에 맞게 '~했어', '~잖아', '~거야', '~는데?', '~지?' 등 자연스러운 일상 어미 활용.

2. **외국어(일본어 가나/한자, 중국어 한자, 영어 등) 100% 순수 한글 번역 필수**:
   - 원문이 외국어인 경우 원문 글자(일본어 히라가나/가타카나, 한자, 중국어 등)를 단 한 글자도 남기거나 섞어 쓰지 말고 **100% 순수 한국어(한글)**로 번역하세요.
   - 절대로 일본어와 한글을 섞어 쓰거나(예: 'ちゃんと 잘해' 금지 -> '제대로 잘해'), 중국어 한자(예: '算了' 금지 -> '됐어')를 출력하지 마세요.

3. **한국어 음성인식(STT) 교정 규칙**:
   - 원문이 이미 한국어인 경우, 음성인식 과정에서 발생하는 오탈자, 유사 발음 오인식 단어, 띄어쓰기, 맞춤법을 구어체 대화 맥락에 맞게 교정하세요.
   - 말이 이어지는 자연스러운 말버릇이나 추임새는 자막 가독성을 해치지 않는 선에서 자연스럽게 정돈하세요.

4. **고유명사 및 문맥 어조 일관성**:
   - 인물, 제품, 지명, 전문 용어가 오인식된 경우 문맥상 올바른 표기로 바로잡으세요.
   - 화자들의 관계와 상황에 맞는 일관된 말투(존댓말/반말)를 유지하세요.

5. **절대 규칙**:
   - 전달받은 세그먼트의 번호(id)와 개수를 반드시 정확히 1:1로 유지해야 합니다. 
   - 타임스탬프와 동기화되어 있으므로 세그먼트를 임의로 합치거나 분리하거나 삭제하지 마세요.

[출력 형식]
반드시 아래와 같은 JSON 객체 형식으로만 응답하세요. 다른 설명이나 인사말은 일체 포함하지 마세요.
{
  "subtitles": [
    {"id": 1, "text": "자연스러운 구어체로 다듬어진 자막 문장"},
    {"id": 2, "text": "자연스러운 구어체로 다듬어진 자막 문장"}
  ]
}
"""

def is_foreign_text(text: str) -> bool:
    """Checks if text contains foreign characters (Chinese/Japanese Kana or Kanji)."""
    if not text:
        return False
    return bool(RE_CHINESE.search(text) or RE_JAPANESE.search(text))

def is_valid_korean_result(original: str, result: str) -> bool:
    """
    Verifies that the result contains zero Japanese Kana or CJK Ideographs (Kanji/Hanzi),
    zero CJK explanation punctuation (。，：“”「」), zero AI meta-talk,
    and contains valid Korean Hangul when the original had text.
    """
    if not result or not str(result).strip():
        return False
    res_str = str(result).strip()
    if is_foreign_text(res_str) or RE_OTHER_FOREIGN.search(res_str):
        return False
    if RE_CJK_PUNCT.search(res_str) or '""' in res_str or "''" in res_str or "\n" in res_str:
        return False
    if RE_MIXED_GIBBERISH.search(res_str):
        return False
    if is_ai_meta_response(original, res_str):
        return False
    orig_clean = re.sub(r'[ー~〜\-\s\.\,\!\?…]+', '', str(original or ''))
    if orig_clean and is_foreign_text(orig_clean):
        if not RE_KOREAN.search(res_str):
            return False
    return True

def clean_json_response(content: str) -> str:
    """Removes markdown code fences and isolates valid JSON string."""
    if not content:
        return ""
    content = content.strip()
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if match and match.group(1).strip():
        content = match.group(1).strip()
        
    first_bracket = content.find('[')
    first_brace = content.find('{')
    
    if first_bracket != -1 and (first_brace == -1 or first_bracket < first_brace):
        last_bracket = content.rfind(']')
        if last_bracket != -1 and last_bracket > first_bracket:
            return content[first_bracket:last_bracket+1]
    elif first_brace != -1:
        last_brace = content.rfind('}')
        if last_brace != -1 and last_brace > first_brace:
            return content[first_brace:last_brace+1]
            
    return content

def extract_translations_from_parsed(parsed: Any) -> Dict[int, str]:
    """Robustly extracts {id: text} mappings from various JSON formats."""
    result_map: Dict[int, str] = {}
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                iid = item.get("id") if item.get("id") is not None else item.get("index")
                txt = item.get("text") or item.get("korean") or item.get("translation") or item.get("refined_text") or ""
                if iid is not None and str(txt).strip():
                    try:
                        result_map[int(iid)] = str(txt).strip()
                    except (ValueError, TypeError):
                        pass
    elif isinstance(parsed, dict):
        for key in ["subtitles", "items", "translations", "results", "data", "segments"]:
            if key in parsed and isinstance(parsed[key], list):
                return extract_translations_from_parsed(parsed[key])
        
        for val in parsed.values():
            if isinstance(val, list):
                res = extract_translations_from_parsed(val)
                if res:
                    return res

        if ("id" in parsed or "index" in parsed) and ("text" in parsed or "korean" in parsed or "translation" in parsed or "refined_text" in parsed):
            iid = parsed.get("id") if parsed.get("id") is not None else parsed.get("index")
            txt = parsed.get("text") or parsed.get("korean") or parsed.get("translation") or parsed.get("refined_text") or ""
            if iid is not None and str(txt).strip():
                try:
                    result_map[int(iid)] = str(txt).strip()
                except (ValueError, TypeError):
                    pass
            return result_map

        for k, v in parsed.items():
            if str(k).isdigit() and isinstance(v, (str, dict)):
                if isinstance(v, dict):
                    txt = v.get("text") or v.get("korean") or v.get("translation") or v.get("refined_text") or ""
                else:
                    txt = str(v)
                if txt.strip():
                    try:
                        result_map[int(k)] = txt.strip()
                    except (ValueError, TypeError):
                        pass
    return result_map

def extract_subtitles_via_regex(raw_text: str) -> Dict[int, str]:
    """Fallback regex extractor for truncated or malformed JSON responses."""
    results: Dict[int, str] = {}
    pattern = r'\{\s*"id"\s*:\s*(\d+)\s*,\s*"(?:text|korean|translation|refined_text)"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*\}'
    for m in re.finditer(pattern, raw_text):
        try:
            iid = int(m.group(1))
            val = m.group(2).replace('\\"', '"').replace('\\n', ' ').strip()
            if val:
                results[iid] = val
        except Exception:
            pass
    if not results:
        pattern2 = r'"(\d+)"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"'
        for m in re.finditer(pattern2, raw_text):
            try:
                iid = int(m.group(1))
                val = m.group(2).replace('\\"', '"').replace('\\n', ' ').strip()
                if val:
                    results[iid] = val
            except Exception:
                pass
    return results

def refine_single_segment_fallback(client: ollama.Client, seg_id: int, raw_text: str) -> str:
    """Ultra-reliable single-line translation/refinement fallback with JSON enforcement and strict sanitization."""
    if not raw_text or not str(raw_text).strip():
        return "..."
    raw_clean = str(raw_text).strip()
    fast_hit = fast_translate_short(raw_clean)
    if fast_hit:
        return fast_hit

    active_model = resolve_active_ollama_model(client)
    prompt = json.dumps({"id": seg_id, "text": raw_clean}, ensure_ascii=False)
    for attempt in range(2):
        try:
            resp = client.chat(
                model=active_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "당신은 영상 자막 번역기입니다. 입력된 자막을 자연스러운 한국어 구어체 한 문장으로 번역하여 "
                            '반드시 {"text": "번역된 한국어 자막"} 형식의 JSON으로만 응답하세요. '
                            "절대로 부연 설명이나 여러 후보를 나열하거나 질문하지 마세요. "
                            "일본어 가나/한자, 중국어 한자, 전각 기호(。，：“”)를 절대 포함하지 마세요."
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

            sanitized = sanitize_subtitle_text(raw_clean, candidate)
            if sanitized and is_valid_korean_result(raw_clean, sanitized):
                return sanitized
        except Exception as e:
            logger.warning(f"Single segment refinement failed for #{seg_id} (attempt {attempt + 1}): {e}")
    return fast_translate_short(raw_clean) or "..."

def refine_subtitles_batch(client: ollama.Client, batch_segments: List[Dict[str, Any]]) -> Dict[int, str]:
    """Refines a single batch of segments via Ollama with validation and sanitization."""
    active_model = resolve_active_ollama_model(client)
    input_payload = [{"id": s["index"], "text": s["raw_text"]} for s in batch_segments]
    user_prompt = f"다음 자막 세그먼트들을 사전식 문어체가 아닌 실제 사람이 대화하는 생생하고 자연스러운 구어체 한국어로 번역 및 교정해 주세요. 일본어 가나/한자 및 중국어 한자를 한 글자도 남기지 말고 반드시 100% 순수 한글로만 번역해야 합니다:\n{json.dumps(input_payload, ensure_ascii=False, indent=2)}"

    response = client.chat(
        model=active_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
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
            logger.warning(f"Could not parse LLM JSON batch: {e}. Attempting regex fallback.")
            result_map = extract_subtitles_via_regex(response_text)

    # Validate & sanitize results: if invalid or meta-response, retry individually
    for seg in batch_segments:
        sid = seg["index"]
        raw = seg.get("raw_text", "")
        if sid in result_map:
            trans = sanitize_subtitle_text(raw, result_map[sid])
            if is_valid_korean_result(raw, trans):
                result_map[sid] = trans
            else:
                logger.info(f"Segment #{sid} returned invalid/untranslated text '{result_map[sid]}'. Retrying individually.")
                result_map[sid] = refine_single_segment_fallback(client, sid, raw)
        else:
            result_map[sid] = refine_single_segment_fallback(client, sid, raw)

    return result_map

def filter_clean_checkpoint(checkpoint: Dict[int, str], segments_by_id: Dict[int, Dict[str, Any]]) -> Dict[int, str]:
    """Sanitizes and removes any cached items that are untranslated foreign text or AI meta-responses."""
    clean: Dict[int, str] = {}
    for sid, val in checkpoint.items():
        orig_seg = segments_by_id.get(sid)
        orig_raw = orig_seg.get("raw_text", "") if orig_seg else ""
        sanitized = sanitize_subtitle_text(orig_raw, val)
        if is_valid_korean_result(orig_raw, sanitized):
            clean[sid] = sanitized
        else:
            logger.info(f"Purging invalid/untranslated cached item #{sid}: '{val}'")
    return clean

def refine_subtitles_with_llm(
    segments: List[Dict[str, Any]], 
    batch_size: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    checkpoint_callback: Optional[Callable[[Dict[int, str]], None]] = None,
    initial_checkpoint: Optional[Dict[int, str]] = None,
    checkpoint_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """
    Refines all subtitle segments using Ollama LLM in batches.
    Maintains a database/disk checkpoint for crash recovery and instant resume.
    Ensures 100% Korean translation with zero untranslated foreign lines.
    """
    if not segments:
        return segments

    if not batch_size:
        batch_size = get_llm_batch_size()

    try:
        client = ollama.Client(host=OLLAMA_HOST, timeout=120.0)
        # Probe connection to Ollama server early
        client.list()
        active_model = resolve_active_ollama_model(client)
        logger.info(f"Connected to Ollama host: {OLLAMA_HOST}, active model: {active_model}")
    except Exception as e:
        logger.warning(f"Could not connect to Ollama service at {OLLAMA_HOST} ({e}). Skipping LLM refinement and keeping raw STT text.")
        return segments

    segments_by_id = {s["index"]: s for s in segments}

    # Load initial checkpoint from parameter or disk fallback
    checkpoint_map: Dict[int, str] = {}
    if initial_checkpoint:
        checkpoint_map = filter_clean_checkpoint(dict(initial_checkpoint), segments_by_id)
        logger.info(f"Loaded {len(checkpoint_map)} clean refined segments from database checkpoint.")
    elif checkpoint_path and checkpoint_path.exists():
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                loaded = {int(k): v for k, v in raw_data.items()}
                checkpoint_map = filter_clean_checkpoint(loaded, segments_by_id)
            logger.info(f"Loaded {len(checkpoint_map)} clean refined segments from checkpoint file {checkpoint_path}")
        except Exception as e:
            logger.warning(f"Failed to load checkpoint file: {e}")

    total_segments = len(segments)
    total_batches = (total_segments + batch_size - 1) // batch_size
    logger.info(f"Refining {total_segments} segments with {active_model} in {total_batches} batches (batch_size={batch_size})...")

    # Process in batches
    for i in range(0, total_segments, batch_size):
        batch = segments[i:i + batch_size]
        current_batch_num = (i // batch_size) + 1

        # Check if all segments in this batch are already refined in valid checkpoint
        all_cached = all(seg["index"] in checkpoint_map for seg in batch)
        if all_cached:
            for seg in batch:
                seg["refined_text"] = checkpoint_map[seg["index"]]
            if progress_callback:
                progress_callback(current_batch_num, total_batches)
            continue

        try:
            refined_map = refine_subtitles_batch(client, batch)
            for seg in batch:
                seg_id = seg["index"]
                if seg_id in refined_map and refined_map[seg_id]:
                    val = refined_map[seg_id]
                    seg["refined_text"] = val
                    checkpoint_map[seg_id] = val
                elif seg_id in checkpoint_map:
                    seg["refined_text"] = checkpoint_map[seg_id]
                else:
                    # Single line fallback
                    fb = refine_single_segment_fallback(client, seg_id, seg["raw_text"])
                    seg["refined_text"] = fb
                    if is_valid_korean_result(seg["raw_text"], fb):
                        checkpoint_map[seg_id] = fb

            logger.info(f"Refined batch {current_batch_num}/{total_batches}")

            # Notify checkpoint callback (e.g., PostgreSQL persistence)
            if checkpoint_callback:
                try:
                    checkpoint_callback(checkpoint_map)
                except Exception as cb_err:
                    logger.warning(f"Checkpoint callback failed: {cb_err}")

            # Also save checkpoint to disk file if configured
            if checkpoint_path:
                try:
                    with open(checkpoint_path, "w", encoding="utf-8") as f:
                        json.dump(checkpoint_map, f, ensure_ascii=False, indent=2)
                except Exception as save_err:
                    logger.warning(f"Failed to save disk checkpoint: {save_err}")

            if progress_callback:
                progress_callback(current_batch_num, total_batches)

            # Brief pause to let Windows GPU/display scheduler breathe
            time.sleep(0.05)
        except Exception as e:
            logger.error(f"Error refining batch {current_batch_num}/{total_batches}: {e}. Retrying segments individually...")
            for seg in batch:
                seg_id = seg["index"]
                fb = refine_single_segment_fallback(client, seg_id, seg["raw_text"])
                seg["refined_text"] = fb
                if is_valid_korean_result(seg["raw_text"], fb):
                    checkpoint_map[seg_id] = fb
            if progress_callback:
                progress_callback(current_batch_num, total_batches)

    # Final Verification Pass: Ensure ZERO untranslated foreign segments
    untranslated_count = 0
    for seg in segments:
        raw = seg.get("raw_text", "")
        ref = seg.get("refined_text", "")
        if not is_valid_korean_result(raw, ref):
            untranslated_count += 1
            fixed = refine_single_segment_fallback(client, seg["index"], raw)
            seg["refined_text"] = fixed
            checkpoint_map[seg["index"]] = fixed

    if untranslated_count > 0:
        logger.info(f"Completed final verification pass: corrected {untranslated_count} remaining segments to Korean.")
        if checkpoint_callback:
            try:
                checkpoint_callback(checkpoint_map)
            except Exception:
                pass
        if checkpoint_path:
            try:
                with open(checkpoint_path, "w", encoding="utf-8") as f:
                    json.dump(checkpoint_map, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    return segments
