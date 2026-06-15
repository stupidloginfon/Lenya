"""Анализ хука: транскрибируем первые секунды ролика и просим Claude оценить,
почему он «залетает», и выдать переиспользуемый шаблон хука.

Оценка складывается из двух частей:
  1. Метрики вовлечённости (лайки/комменты к просмотрам) — объективный сигнал.
  2. Разбор Claude по тексту хука — насколько силён сам приём.
"""
import json
from pathlib import Path
from typing import Optional

import anthropic

import config
from pipeline import db, ffmpeg_utils

# Сколько секунд от начала считаем «хуком».
HOOK_SECONDS = 5.0

_HOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "hook_type": {"type": "string", "description": "Тип приёма: вопрос, интрига, шок, обещание результата и т.п."},
        "why_it_works": {"type": "string"},
        "hook_score": {"type": "number", "description": "0-100, насколько силён хук"},
        "reusable_template": {
            "type": "string",
            "description": "Шаблон хука с плейсхолдерами вида [тема], [результат] для генерации новых видео",
        },
        "suggested_topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook_type", "why_it_works", "hook_score", "reusable_template", "suggested_topics"],
    "additionalProperties": False,
}


def _engagement_score(row) -> Optional[float]:
    """Грубая оценка вовлечённости 0-100 по метрикам (если они есть)."""
    views = row["views"] or 0
    if views < 1:
        return None
    likes = row["likes"] or 0
    comments = row["comments"] or 0
    rate = (likes + 3 * comments) / views  # комменты весомее лайков
    # Виральные шортсы дают engagement rate ~10%+; нормируем к 100.
    return min(100.0, rate * 1000)


def transcribe_hook(video_path: Path) -> str:
    """Текст первых HOOK_SECONDS секунд. Пусто, если faster-whisper не установлен."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("[analyze] faster-whisper не установлен — пропускаю транскрипцию хука")
        return ""

    config.ensure_dirs()
    hook_clip = config.DOWNLOADS_DIR / f"{video_path.stem}_hook.mp4"
    hook_wav = config.DOWNLOADS_DIR / f"{video_path.stem}_hook.wav"
    ffmpeg_utils.extract_clip(video_path, hook_clip, 0, HOOK_SECONDS)
    ffmpeg_utils.extract_audio(hook_clip, hook_wav)

    model = WhisperModel(config.WHISPER_MODEL, device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(hook_wav))
    return " ".join(seg.text.strip() for seg in segments).strip()


def _ask_claude(hook_text: str, row) -> dict:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    context = (
        f"Платформа: {row['platform']}\n"
        f"Заголовок: {row['title']}\n"
        f"Просмотры: {row['views']}, лайки: {row['likes']}, комментарии: {row['comments']}\n"
        f"Текст хука (первые {HOOK_SECONDS:.0f} сек): {hook_text or '(нет транскрипции)'}"
    )
    resp = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2000,
        system=(
            "Ты — эксперт по короткому видеоконтенту (TikTok/Shorts/Reels). "
            "Анализируешь хук (первые секунды) и оцениваешь его виральный потенциал. "
            "Отвечай строго по схеме."
        ),
        messages=[{"role": "user", "content": context}],
        output_config={"format": {"type": "json_schema", "schema": _HOOK_SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def analyze(video_id: int) -> dict:
    """Полный разбор одного ролика. Пишет результат и стадию в БД."""
    row = db.get(video_id)
    if row is None or not row["download_path"]:
        raise ValueError(f"video {video_id}: сначала скачай ролик (download)")

    hook_text = transcribe_hook(Path(row["download_path"]))
    analysis = _ask_claude(hook_text, row)

    claude_score = float(analysis.get("hook_score", 0))
    eng = _engagement_score(row)
    # Если метрики есть — усредняем с оценкой Claude, иначе берём только Claude.
    final = round((claude_score + eng) / 2, 1) if eng is not None else round(claude_score, 1)
    analysis["engagement_score"] = eng
    analysis["final_score"] = final

    db.set_analysis(video_id, hook_text, final, analysis)
    verdict = "ПРИНЯТ" if final >= config.HOOK_SCORE_THRESHOLD else "отклонён"
    print(f"[analyze] [{video_id}] хук={final} ({verdict}) — {analysis['hook_type']}")
    return analysis
