import json
import logging
import re
import time
from typing import List, Dict, Any, Optional
import httpx
import ollama

from app.config import (
    OLLAMA_HOST,
    get_runtime_settings,
    get_active_llm_provider,
)

logger = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "ollama": "qwen2.5:14b",
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-sonnet-latest",
    "gemini": "gemini-2.5-flash",
}

AVAILABLE_MODELS_CATALOG = {
    "openai": ["gpt-4o", "gpt-4o-mini", "o3-mini", "gpt-4-turbo"],
    "anthropic": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-pro", "gemini-1.5-flash"],
}


def get_provider_models(provider: str) -> List[str]:
    """Returns the list of recommended/supported models for the given provider."""
    p = (provider or "").strip().lower()
    if p == "ollama":
        try:
            c = ollama.Client(host=OLLAMA_HOST, timeout=5.0)
            resp = c.list()
            raw_models = resp.get("models", []) if isinstance(resp, dict) else getattr(resp, "models", [])
            installed = []
            for m in raw_models:
                name = m.get("model") or m.get("name") if isinstance(m, dict) else (getattr(m, "model", None) or getattr(m, "name", None))
                if name:
                    installed.append(str(name))
            if installed:
                return installed
        except Exception:
            pass
        return ["qwen2.5:14b", "qwen2.5:7b", "llama3.1:8b", "mistral:latest"]
    return AVAILABLE_MODELS_CATALOG.get(p, [])


def _clean_json_str(content: str) -> str:
    """Removes markdown backticks and extracts inner json."""
    if not content:
        return ""
    c = content.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", c)
    if match and match.group(1).strip():
        c = match.group(1).strip()
    return c


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504, 529}


def _post_with_retry(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: float,
    provider_label: str,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """
    Executes HTTP POST to cloud LLM provider with exponential backoff for:
    - HTTP 429 (Rate Limit, honoring Retry-After header if present)
    - HTTP 5xx (500, 502, 503, 504, 529 transient server errors)
    - Network timeouts / transient socket errors (httpx.TimeoutException, httpx.RequestError)
    Fails fast on authentication (401/403) or invalid request/context overflow (400).
    """
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=payload)

            if resp.status_code == 200:
                return resp.json()

            err_body = resp.text
            try:
                err_json = resp.json()
                if isinstance(err_json.get("error"), dict):
                    err_body = err_json["error"].get("message") or err_body
                elif err_json.get("error"):
                    err_body = str(err_json["error"])
            except Exception:
                pass

            if resp.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries - 1:
                retry_after = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
                wait_sec = 1.5 * (2 ** attempt)
                if retry_after:
                    try:
                        wait_sec = min(15.0, max(wait_sec, float(retry_after)))
                    except ValueError:
                        pass
                logger.warning(
                    f"[{provider_label}] HTTP {resp.status_code} ({err_body[:120]}). "
                    f"Retrying in {wait_sec:.1f}s (attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(wait_sec)
                continue

            if resp.status_code in (401, 403):
                raise ValueError(f"{provider_label} 인증 오류 ({resp.status_code}): API 키가 유효하지 않거나 권한이 없습니다. ({err_body})")
            raise RuntimeError(f"{provider_label} API 오류 ({resp.status_code}): {err_body}")

        except (httpx.TimeoutException, httpx.RequestError) as net_err:
            last_err = net_err
            if attempt < max_retries - 1:
                wait_sec = 1.5 * (2 ** attempt)
                logger.warning(
                    f"[{provider_label}] Network/Timeout error ({net_err}). "
                    f"Retrying in {wait_sec:.1f}s (attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(wait_sec)
                continue
            raise RuntimeError(f"{provider_label} 네트워크 타임아웃/연결 오류: {net_err}") from net_err

    raise RuntimeError(f"{provider_label} 호출 실패: {last_err}")


def chat_completion(
    messages: List[Dict[str, str]],
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
    format_json: bool = False,
    max_tokens: int = 2048,
    timeout: float = 90.0,
    api_key_override: Optional[str] = None,
    max_retries: int = 3,
) -> str:
    """
    Unified LLM chat completion caller with exponential backoff retry supporting:
    - Ollama (Local)
    - OpenAI (GPT-4o, GPT-4o-mini, etc.)
    - Anthropic (Claude-3.5-Sonnet, Claude-3.5-Haiku, etc.)
    - Google Gemini (Gemini-2.5-Flash, Gemini-2.5-Pro, etc.)
    """
    settings = get_runtime_settings(mask_keys=False)
    p = (provider or settings.get("llm_provider") or "ollama").strip().lower()

    # 1. Ollama
    if p == "ollama":
        target_model = model or settings.get("ollama_model") or DEFAULT_MODELS["ollama"]
        options: Dict[str, Any] = {
            "temperature": temperature,
            "top_p": 0.9,
            "repeat_penalty": 1.15,
            "num_predict": max_tokens,
            "num_ctx": 4096,
        }
        kwargs: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "options": options,
            "think": False,
        }
        if format_json:
            kwargs["format"] = "json"

        last_ollama_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                client = ollama.Client(host=OLLAMA_HOST, timeout=timeout)
                resp = client.chat(**kwargs)
                if isinstance(resp, dict):
                    return (resp.get("message", {}).get("content") or "").strip()
                msg_obj = getattr(resp, "message", None)
                return (getattr(msg_obj, "content", "") or "").strip()
            except Exception as e:
                last_ollama_err = e
                err_str = str(e).lower()
                # Do not retry if model does not exist locally
                if "not found" in err_str and "model" in err_str:
                    raise RuntimeError(f"Ollama 모델 '{target_model}'이(가) 설치되어 있지 않습니다: {e}") from e
                if attempt < max_retries - 1:
                    wait_sec = 1.5 * (2 ** attempt)
                    logger.warning(f"[Ollama] 호출 일시 오류 ({e}). {wait_sec:.1f}초 후 재시도 ({attempt + 1}/{max_retries})...")
                    time.sleep(wait_sec)
                    continue
                raise RuntimeError(f"Ollama 호출 오류: {e}") from e
        raise RuntimeError(f"Ollama 호출 실패: {last_ollama_err}")

    # 2. OpenAI
    elif p == "openai":
        api_key = api_key_override or settings.get("openai_api_key", "").strip()
        if not api_key:
            raise ValueError("OpenAI API 키가 설정되지 않았습니다. 관리자 설정에서 API 키를 등록해 주세요.")
        target_model = model or settings.get("openai_model") or DEFAULT_MODELS["openai"]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if format_json:
            payload["response_format"] = {"type": "json_object"}

        data = _post_with_retry(
            url="https://api.openai.com/v1/chat/completions",
            headers=headers,
            payload=payload,
            timeout=timeout,
            provider_label="OpenAI",
            max_retries=max_retries,
        )
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("OpenAI API 응답이 비어 있습니다.")
        return (choices[0].get("message", {}).get("content") or "").strip()

    # 3. Anthropic (Claude)
    elif p == "anthropic":
        api_key = api_key_override or settings.get("anthropic_api_key", "").strip()
        if not api_key:
            raise ValueError("Anthropic API 키가 설정되지 않았습니다. 관리자 설정에서 API 키를 등록해 주세요.")
        target_model = model or settings.get("anthropic_model") or DEFAULT_MODELS["anthropic"]

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        # Claude separates system instruction from messages
        system_prompt = ""
        claude_messages = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                if system_prompt:
                    system_prompt += "\n\n" + content
                else:
                    system_prompt = content
            else:
                claude_messages.append({
                    "role": "user" if role == "user" else "assistant",
                    "content": content
                })

        # Anthropic requires at least one user message
        if not claude_messages:
            claude_messages.append({"role": "user", "content": "Please proceed."})

        payload = {
            "model": target_model,
            "messages": claude_messages,
            "max_tokens": max(max_tokens, 1024),
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt

        data = _post_with_retry(
            url="https://api.anthropic.com/v1/messages",
            headers=headers,
            payload=payload,
            timeout=timeout,
            provider_label="Anthropic",
            max_retries=max_retries,
        )
        contents = data.get("content", [])
        if not contents:
            raise RuntimeError("Anthropic Claude 응답이 비어 있습니다.")
        return (contents[0].get("text") or "").strip()

    # 4. Google Gemini
    elif p in ("gemini", "google"):
        api_key = api_key_override or settings.get("gemini_api_key", "").strip()
        if not api_key:
            raise ValueError("Gemini API 키가 설정되지 않았습니다. 관리자 설정에서 API 키를 등록해 주세요.")
        target_model = model or settings.get("gemini_model") or DEFAULT_MODELS["gemini"]

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }

        system_parts: List[str] = []
        gemini_contents = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                if content:
                    system_parts.append(content)
            else:
                gemini_role = "user" if role == "user" else "model"
                gemini_contents.append({"role": gemini_role, "parts": [{"text": content}]})

        if not gemini_contents:
            gemini_contents.append({"role": "user", "parts": [{"text": "Please proceed."}]})

        gen_config: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if format_json:
            gen_config["responseMimeType"] = "application/json"

        payload: Dict[str, Any] = {
            "contents": gemini_contents,
            "generationConfig": gen_config,
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

        data = _post_with_retry(
            url=url,
            headers=headers,
            payload=payload,
            timeout=timeout,
            provider_label="Gemini",
            max_retries=max_retries,
        )
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini API 응답이 비어 있습니다.")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise RuntimeError("Gemini API 텍스트 본문이 비어 있습니다.")
        return (parts[0].get("text") or "").strip()

    else:
        raise ValueError(f"지원하지 않는 LLM Provider입니다: {provider}")


def test_provider_connectivity(
    provider: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Tests connectivity to the designated provider and model."""
    p = (provider or "").strip().lower()
    t0 = time.time()
    try:
        reply = chat_completion(
            messages=[
                {"role": "system", "content": "You are a connectivity test assistant. Always reply with only: OK"},
                {"role": "user", "content": "Ping test."},
            ],
            provider=p,
            model=model,
            temperature=0.1,
            max_tokens=20,
            timeout=15.0,
            api_key_override=api_key if api_key and not api_key.startswith("***") else None,
        )
        latency_ms = int(round((time.time() - t0) * 1000))
        return {
            "success": True,
            "provider": p,
            "model": model or DEFAULT_MODELS.get(p, "default"),
            "latency_ms": latency_ms,
            "reply": reply[:100],
            "message": f"연결 성공 ({latency_ms}ms)"
        }
    except Exception as e:
        latency_ms = int(round((time.time() - t0) * 1000))
        logger.warning(f"Connectivity test failed for {p}: {e}")
        return {
            "success": False,
            "provider": p,
            "model": model or DEFAULT_MODELS.get(p, "default"),
            "latency_ms": latency_ms,
            "error": str(e),
            "message": f"연결 실패: {str(e)}"
        }

