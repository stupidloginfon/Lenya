"""Вставка рекламы в сгенерированное видео.

Два независимых механизма (оба опциональны, настраиваются в .env):
  1. AD_TEXT — баннер с call-to-action поверх всего видео (drawtext).
  2. AD_CLIP — готовый рекламный ролик, который вклеивается в конец (concat).
Если ни то, ни другое не задано — видео остаётся без изменений.
"""
from pathlib import Path
from typing import Optional

import config
from pipeline import db, ffmpeg_utils

# Где искать шрифт для баннера (drawtext требует ttf).
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def _find_font() -> Optional[str]:
    for f in _FONT_CANDIDATES:
        if Path(f).exists():
            return f
    return None


def _overlay_text(src: Path, dst: Path, text: str) -> Path:
    font = _find_font()
    if not font:
        print("[advertise] не нашёл ttf-шрифт для баннера — пропускаю AD_TEXT")
        return src
    safe = text.replace(":", r"\:").replace("'", r"\\'")
    drawtext = (
        f"drawtext=fontfile='{font}':text='{safe}':"
        "fontcolor=white:fontsize=46:box=1:boxcolor=black@0.55:boxborderw=18:"
        "x=(w-text_w)/2:y=h*0.82"
    )
    ffmpeg_utils.run([
        "ffmpeg", "-y", "-i", str(src), "-vf", drawtext,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", str(dst),
    ])
    return dst


def _append_clip(src: Path, dst: Path, ad_clip: Path) -> Path:
    # Приводим оба ролика к 1080x1920/30fps/стерео и склеиваем через concat-фильтр.
    norm = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,fps=30,format=yuv420p"
    )
    ffmpeg_utils.run([
        "ffmpeg", "-y", "-i", str(src), "-i", str(ad_clip),
        "-filter_complex",
        f"[0:v]{norm}[v0];[1:v]{norm}[v1];"
        "[0:a]aresample=44100,aformat=channel_layouts=stereo[a0];"
        "[1:a]aresample=44100,aformat=channel_layouts=stereo[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(dst),
    ])
    return dst


def advertise(video_id: int) -> Path:
    """Наложить рекламу на сгенерированный ролик. Возвращает путь к итогу."""
    ffmpeg_utils.ensure_ffmpeg()
    row = db.get(video_id)
    if row is None or not row["output_path"]:
        raise ValueError(f"video {video_id}: сначала сгенерируй видео (generate)")

    current = Path(row["output_path"])

    if config.AD_TEXT:
        out = config.OUTPUTS_DIR / f"{video_id}_ad_text.mp4"
        current = _overlay_text(current, out, config.AD_TEXT)

    if config.AD_CLIP and Path(config.AD_CLIP).exists():
        out = config.OUTPUTS_DIR / f"{video_id}_ad_full.mp4"
        current = _append_clip(current, out, Path(config.AD_CLIP))
    elif config.AD_CLIP:
        print(f"[advertise] AD_CLIP={config.AD_CLIP} не найден — пропускаю вклейку")

    db.update(video_id, output_path=str(current), status="advertised")
    print(f"[advertise] [{video_id}] -> {current}")
    return current
