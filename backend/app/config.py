import os
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PROCESSED_DIR = DATA_DIR / "processed"
SETTINGS_FILE = DATA_DIR / "settings.json"

# Load environment variables from .env files (.env at ROOT_DIR or BASE_DIR)
_env_loaded = False
for env_path in [ROOT_DIR / ".env", BASE_DIR / ".env"]:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
        _env_loaded = True
        break
if not _env_loaded:
    load_dotenv()  # Fallback to current working directory

# Ensure directories exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Server Configs
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# Service Configs (Defaults)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
LLM_BATCH_SIZE = int(os.getenv("LLM_BATCH_SIZE", "10"))

# Multi-Cloud LLM Configs
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

# Whisper Configs (GPU CUDA Acceleration by default, large-v3-turbo)
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "large-v3-turbo")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")

# Database Configs (Auto-detects postgres if configured, otherwise defaults to 'sqlite' for zero-config)
_raw_db_type = os.getenv("DB_TYPE", "").strip().lower()
if _raw_db_type:
    DB_TYPE = _raw_db_type
elif os.getenv("POSTGRES_PASSWORD") or (os.getenv("POSTGRES_HOST") and os.getenv("POSTGRES_HOST") not in ("localhost", "127.0.0.1")):
    DB_TYPE = "postgres"
else:
    DB_TYPE = "sqlite"

SQLITE_PATH = os.getenv("SQLITE_PATH", str(DATA_DIR / "transm.db"))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# PostgreSQL Database Configs (Used when DB_TYPE=postgres)
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "transm")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

# Media scan root directories for server-side search
def get_media_scan_dirs() -> List[Path]:
    raw_dirs = os.getenv("MEDIA_SCAN_DIRS", "")
    if raw_dirs.strip():
        parts = [p.strip() for p in raw_dirs.replace(";", ",").split(",") if p.strip()]
        return [Path(p) for p in parts]
    # Default fallback directories if not set in .env
    default_candidates = [
        r"D:\Videos",
        r"D:\Media",
    ]
    return [Path(p) for p in default_candidates if Path(p).exists()]

def mask_api_key(key: Optional[str]) -> str:
    """Masks an API key for safe UI display (e.g., sk-...abcd or ********)."""
    if not key or not str(key).strip():
        return ""
    k = str(key).strip()
    if len(k) <= 8:
        return "********"
    return f"{k[:3]}...{k[-4:]}"


def is_masked_key(key: Optional[str]) -> bool:
    """Detects whether a key string is an already-masked placeholder."""
    if not key:
        return False
    k = str(key).strip()
    return bool(re.search(r"^\*{4,}|^\w{1,6}\.\.\.\w{1,6}$", k))


# Runtime Dynamic Settings Cache
_runtime_settings: Dict[str, Any] = {}


def get_runtime_settings(mask_keys: bool = False) -> Dict[str, Any]:
    """Loads runtime settings from disk or returns defaults."""
    global _runtime_settings
    defaults = {
        "ollama_model": OLLAMA_MODEL,
        "llm_batch_size": LLM_BATCH_SIZE,
        "whisper_model_size": WHISPER_MODEL_SIZE,
        "whisper_device": WHISPER_DEVICE,
        "whisper_compute_type": WHISPER_COMPUTE_TYPE,
        "llm_provider": LLM_PROVIDER,
        "openai_api_key": OPENAI_API_KEY,
        "openai_model": OPENAI_MODEL,
        "anthropic_api_key": ANTHROPIC_API_KEY,
        "anthropic_model": ANTHROPIC_MODEL,
        "gemini_api_key": GEMINI_API_KEY,
        "gemini_model": GEMINI_MODEL,
    }
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    defaults.update(saved)
        except Exception:
            pass
    _runtime_settings = defaults

    if mask_keys:
        masked = dict(_runtime_settings)
        masked["openai_api_key"] = mask_api_key(masked.get("openai_api_key"))
        masked["anthropic_api_key"] = mask_api_key(masked.get("anthropic_api_key"))
        masked["gemini_api_key"] = mask_api_key(masked.get("gemini_api_key"))
        return masked

    return _runtime_settings


def update_runtime_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Updates runtime settings and persists them to settings.json."""
    global _runtime_settings, OLLAMA_MODEL, LLM_BATCH_SIZE, WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE
    global LLM_PROVIDER, OPENAI_API_KEY, OPENAI_MODEL, ANTHROPIC_API_KEY, ANTHROPIC_MODEL, GEMINI_API_KEY, GEMINI_MODEL
    current = get_runtime_settings(mask_keys=False)

    standard_keys = (
        "ollama_model", "whisper_model_size", "whisper_device", "whisper_compute_type",
        "llm_provider", "openai_model", "anthropic_model", "gemini_model"
    )
    for k in standard_keys:
        if k in updates and updates[k] is not None:
            current[k] = str(updates[k]).strip()

    if "llm_batch_size" in updates and updates["llm_batch_size"] is not None:
        try:
            current["llm_batch_size"] = max(1, min(50, int(updates["llm_batch_size"])))
        except (ValueError, TypeError):
            pass

    # Sensitive API Keys: Only update if non-empty and not masked placeholder
    for key_field in ("openai_api_key", "anthropic_api_key", "gemini_api_key"):
        if key_field in updates and updates[key_field] is not None:
            val = str(updates[key_field]).strip()
            # If user explicitly cleared it or entered a new non-masked key
            if val == "" or not is_masked_key(val):
                current[key_field] = val

    _runtime_settings = current
    OLLAMA_MODEL = current["ollama_model"]
    LLM_BATCH_SIZE = current["llm_batch_size"]
    WHISPER_MODEL_SIZE = current["whisper_model_size"]
    WHISPER_DEVICE = current["whisper_device"]
    WHISPER_COMPUTE_TYPE = current["whisper_compute_type"]

    LLM_PROVIDER = current.get("llm_provider", "ollama")
    OPENAI_API_KEY = current.get("openai_api_key", "")
    OPENAI_MODEL = current.get("openai_model", "gpt-4o")
    ANTHROPIC_API_KEY = current.get("anthropic_api_key", "")
    ANTHROPIC_MODEL = current.get("anthropic_model", "claude-3-5-sonnet-latest")
    GEMINI_API_KEY = current.get("gemini_api_key", "")
    GEMINI_MODEL = current.get("gemini_model", "gemini-2.5-flash")

    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return current


def get_active_llm_provider() -> str:
    return get_runtime_settings().get("llm_provider", LLM_PROVIDER).strip().lower()


def get_active_llm_config() -> Dict[str, Any]:
    s = get_runtime_settings()
    prov = s.get("llm_provider", "ollama").strip().lower()
    return {
        "provider": prov,
        "ollama_host": OLLAMA_HOST,
        "ollama_model": s.get("ollama_model", OLLAMA_MODEL),
        "openai_api_key": s.get("openai_api_key", OPENAI_API_KEY),
        "openai_model": s.get("openai_model", OPENAI_MODEL),
        "anthropic_api_key": s.get("anthropic_api_key", ANTHROPIC_API_KEY),
        "anthropic_model": s.get("anthropic_model", ANTHROPIC_MODEL),
        "gemini_api_key": s.get("gemini_api_key", GEMINI_API_KEY),
        "gemini_model": s.get("gemini_model", GEMINI_MODEL),
        "batch_size": int(s.get("llm_batch_size", LLM_BATCH_SIZE)),
    }


def get_ollama_model() -> str:
    return get_runtime_settings().get("ollama_model", OLLAMA_MODEL)


def get_llm_batch_size() -> int:
    return int(get_runtime_settings().get("llm_batch_size", LLM_BATCH_SIZE))


def get_whisper_config() -> Dict[str, str]:
    s = get_runtime_settings()
    return {
        "model_size": s.get("whisper_model_size", WHISPER_MODEL_SIZE),
        "device": s.get("whisper_device", WHISPER_DEVICE),
        "compute_type": s.get("whisper_compute_type", WHISPER_COMPUTE_TYPE),
    }
