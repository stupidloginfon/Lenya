"""Скачивание исходного ролика и его полных метаданных через yt-dlp."""
from pathlib import Path
from typing import Any

import yt_dlp

import config
from pipeline import db


def download(video_id: int) -> Path:
    """Скачать один ролик по записи из БД. Возвращает путь к mp4."""
    row = db.get(video_id)
    if row is None:
        raise ValueError(f"video {video_id} не найден")
    if row["download_path"] and Path(row["download_path"]).exists():
        return Path(row["download_path"])

    config.ensure_dirs()
    out_tmpl = str(config.DOWNLOADS_DIR / f"{video_id}.%(ext)s")
    opts = {
        "quiet": True,
        "outtmpl": out_tmpl,
        # Приводим к mp4 (h264/aac) — дальше с ним работает ffmpeg.
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(row["source_url"], download=True)
        path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")

    # Обновим метрики — на flat-этапе их часто нет.
    db.update(
        video_id,
        download_path=str(path),
        title=info.get("title") or row["title"],
        author=info.get("uploader") or row["author"],
        views=info.get("view_count") or row["views"],
        likes=info.get("like_count") or row["likes"],
        comments=info.get("comment_count") or row["comments"],
        duration=info.get("duration") or row["duration"],
    )
    print(f"[download] [{video_id}] -> {path}")
    return path
