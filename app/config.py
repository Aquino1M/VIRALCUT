from __future__ import annotations

import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# Accept the deployment-level secret file when the application is unpacked in a nested folder.
load_dotenv(BASE_DIR / ".env" if (BASE_DIR / ".env").exists() else BASE_DIR.parent / ".env")


def parse_worker_origins(value: str) -> list[str]:
    origins: list[str] = []
    for raw in (value or "").split(","):
        origin = raw.strip().rstrip("/")
        if not origin or origin == "*":
            continue
        if not origin.startswith(("http://", "https://")):
            continue
        if origin not in origins:
            origins.append(origin)
    return origins

APP_NAME = os.getenv("APP_NAME", "ViralClip AI")

def _persistent_secret() -> str:
    configured = os.getenv("SECRET_KEY", "").strip()
    if configured and configured != "dev-change-me":
        return configured
    data_root = BASE_DIR / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    key_path = data_root / ".session_secret"
    try:
        if key_path.exists():
            value = key_path.read_text(encoding="utf-8").strip()
            if len(value) >= 32:
                return value
        value = secrets.token_urlsafe(48)
        key_path.write_text(value, encoding="utf-8")
        return value
    except Exception:
        return secrets.token_urlsafe(48)

SECRET_KEY = _persistent_secret()
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8080"))
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.getenv("FFPROBE_BIN", "ffprobe")
WHISPER_BACKEND = os.getenv("WHISPER_BACKEND", "auto")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "3"))
WHISPER_NUM_WORKERS = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "1"))
WHISPER_CHUNK_SECONDS = int(os.getenv("WHISPER_CHUNK_SECONDS", "60"))
ASR_CACHE_MAX_GB = float(os.getenv("ASR_CACHE_MAX_GB", "8"))
VIDEO_ENCODER = os.getenv("VIDEO_ENCODER", "auto")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10240"))
WORKER_ALLOWED_ORIGINS = parse_worker_origins(os.getenv("WORKER_ALLOWED_ORIGINS", ""))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

# ViralClip V4.2 Adaptive Compute Fabric. Lightning is acceleration only and
# is hard-locked to the free CPU worker. No SDK code starts GPUs or paid machines.
LIGHTNING_ENABLED = os.getenv("LIGHTNING_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
LIGHTNING_CLOUD_URL = os.getenv("LIGHTNING_CLOUD_URL", "").strip().rstrip("/")
LIGHTNING_CLOUD_TOKEN = os.getenv("LIGHTNING_CLOUD_TOKEN", "").strip()
LIGHTNING_FREE_CPU_ONLY = True
LIGHTNING_TIMEOUT = max(10, int(os.getenv("LIGHTNING_TIMEOUT", "120")))
LIGHTNING_UPLOAD_CHUNK_MB = max(1, min(64, int(os.getenv("LIGHTNING_UPLOAD_CHUNK_MB", "16"))))
COMPUTE_MODE = os.getenv("COMPUTE_MODE", "auto").strip().lower() or "auto"
CLOUD_MEDIA_RETENTION_HOURS = max(1, int(os.getenv("CLOUD_MEDIA_RETENTION_HOURS", "24")))
CLOUD_RESULT_RETENTION_DAYS = max(1, int(os.getenv("CLOUD_RESULT_RETENTION_DAYS", "7")))

DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
THUMB_DIR = DATA_DIR / "thumbs"
TEMP_DIR = DATA_DIR / "temp"
FONT_DIR = DATA_DIR / "fonts"
PREVIEW_DIR = DATA_DIR / "previews"
BRAND_DIR = DATA_DIR / "brand"
ASSET_DIR = DATA_DIR / "assets"
LOG_DIR = DATA_DIR / "logs"
TRACK_DIR = DATA_DIR / "tracks"
TRACK_MODEL_DIR = DATA_DIR / "models" / "tracking"
DB_PATH = DATA_DIR / "viralclip.db"

for d in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR, THUMB_DIR, TEMP_DIR, FONT_DIR, PREVIEW_DIR, BRAND_DIR, ASSET_DIR, LOG_DIR, TRACK_DIR, TRACK_MODEL_DIR):
    d.mkdir(parents=True, exist_ok=True)
