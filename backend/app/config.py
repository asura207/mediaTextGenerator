import os
import json
from pathlib import Path
from typing import Dict, Any, List
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

# Runtime Dynamic Settings Cache
_runtime_settings: Dict[str, Any] = {}


def get_runtime_settings() -> Dict[str, Any]:
    """Loads runtime settings from disk or returns defaults."""
    global _runtime_settings
    defaults = {
        "ollama_model": OLLAMA_MODEL,
        "llm_batch_size": LLM_BATCH_SIZE,
        "whisper_model_size": WHISPER_MODEL_SIZE,
        "whisper_device": WHISPER_DEVICE,
        "whisper_compute_type": WHISPER_COMPUTE_TYPE,
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
    return _runtime_settings


def update_runtime_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Updates runtime settings and persists them to settings.json."""
    global _runtime_settings, OLLAMA_MODEL, LLM_BATCH_SIZE, WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE
    current = get_runtime_settings()
    for k in ("ollama_model", "llm_batch_size", "whisper_model_size", "whisper_device", "whisper_compute_type"):
        if k in updates and updates[k] is not None:
            if k == "llm_batch_size":
                current[k] = max(1, min(50, int(updates[k])))
            else:
                current[k] = str(updates[k]).strip()

    _runtime_settings = current
    OLLAMA_MODEL = current["ollama_model"]
    LLM_BATCH_SIZE = current["llm_batch_size"]
    WHISPER_MODEL_SIZE = current["whisper_model_size"]
    WHISPER_DEVICE = current["whisper_device"]
    WHISPER_COMPUTE_TYPE = current["whisper_compute_type"]

    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return current


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
