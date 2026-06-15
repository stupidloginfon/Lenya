"""Конфигурация пайплайна: читается из .env (или переменных окружения)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


# --- Claude ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")

# --- Папки ---
DATA_DIR = _path(os.getenv("DATA_DIR", "./data"))
BROLL_DIR = _path(os.getenv("BROLL_DIR", "./assets/broll"))

DOWNLOADS_DIR = DATA_DIR / "downloads"     # скачанные исходники
OUTPUTS_DIR = DATA_DIR / "outputs"         # сгенерированные видео
DB_PATH = DATA_DIR / "lenya.db"

# --- Озвучка ---
TTS_VOICE = os.getenv("TTS_VOICE", "ru-RU-DmitryNeural")

# --- Реклама ---
AD_TEXT = os.getenv("AD_TEXT", "")
AD_CLIP = os.getenv("AD_CLIP", "")

# --- Транскрипция ---
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# --- Загрузка ---
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "./client_secret.json")
TIKTOK_ACCESS_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN", "")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "")
IG_USER_ID = os.getenv("IG_USER_ID", "")

# Порог «залетевшего» хука: видео ниже него не считаем виральным.
HOOK_SCORE_THRESHOLD = float(os.getenv("HOOK_SCORE_THRESHOLD", "70"))


def ensure_dirs() -> None:
    """Создать рабочие папки, если их ещё нет."""
    for d in (DATA_DIR, DOWNLOADS_DIR, OUTPUTS_DIR, BROLL_DIR):
        d.mkdir(parents=True, exist_ok=True)
