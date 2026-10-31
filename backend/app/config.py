"""Configuration.

Load order (first wins): real environment variables > <project>/.env > ~/.fieldnotes/config.env
The API key is saved once in ~/.fieldnotes/config.env (`python manage.py set-key gsk_...`),
so replacing or re-extracting the project never asks for it again.
Data (database + audio) also lives in ~/.fieldnotes/data by default, so updates never lose recordings."""
import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
HOME_DIR = Path(os.environ.get("FIELDNOTES_HOME") or (Path.home() / ".fieldnotes"))
USER_CONFIG = HOME_DIR / "config.env"

_FILES = [dotenv_values(f) for f in (ROOT / ".env", USER_CONFIG) if f.is_file()]


def env(name: str, default: str | None = None) -> str | None:
    """First non-empty value: environment, project .env, user config."""
    v = os.environ.get(name)
    if v not in (None, ""):
        return v
    for f in _FILES:
        v = f.get(name)
        if v not in (None, ""):
            return v
    return default


def _path(name: str, default: Path) -> Path:
    return Path(env(name) or default)


def _int(name: str, default: int) -> int:
    try:
        return int(env(name) or default)
    except ValueError:
        return default


DATA_DIR = _path("DATA_DIR", HOME_DIR / "data")
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = _path("DB_PATH", DATA_DIR / "app.db")
SAMPLE_DIR = _path("SAMPLE_DIR", ROOT / "sample-recordings")

# Speech to text: groq | local | fake
ASR_PROVIDER = env("ASR_PROVIDER") or "groq"
ASR_FALLBACK = env("ASR_FALLBACK") or ""  # "local" -> faster-whisper if Groq fails
ASR_LANGUAGE = env("ASR_LANGUAGE") or None  # en | hi | bn ; empty = auto-detect
GROQ_API_KEY = (env("GROQ_API_KEY") or "").strip()
GROQ_ASR_MODEL = env("GROQ_ASR_MODEL") or "whisper-large-v3"
WHISPER_MODEL = env("WHISPER_MODEL") or "small"

# LLM: any OpenAI-compatible chat endpoint (Groq by default) | fake
LLM_PROVIDER = env("LLM_PROVIDER") or "openai_compat"
LLM_BASE_URL = env("LLM_BASE_URL") or "https://api.groq.com/openai/v1"
LLM_API_KEY = (env("LLM_API_KEY") or "").strip() or GROQ_API_KEY
LLM_MODEL = env("LLM_MODEL") or "openai/gpt-oss-120b"

TIMEZONE = env("APP_TIMEZONE") or "Asia/Kolkata"
CORS_ORIGINS = [o.strip() for o in (env("CORS_ORIGINS") or
                "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
WORKER_ENABLED = (env("WORKER_ENABLED") or "1") == "1"
MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 200)
DASHBOARD_DEVICE_ID = "dashboard"
ABSTAIN = "The recordings don't contain this."
