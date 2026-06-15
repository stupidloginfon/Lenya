"""Поиск трендовых роликов в TikTok / YouTube Shorts / Instagram Reels.

Используем yt-dlp в режиме «только метаданные» (без скачивания файлов): он умеет
разворачивать страницы хэштегов/каналов и поисковую выдачу в список роликов.
Каждый найденный ролик складываем в БД со стадией `discovered`.
"""
from typing import Any, Iterable

import yt_dlp

from pipeline import db


def _yt_search_url(query: str, limit: int) -> str:
    # ytsearchN: — встроенный «поиск по YouTube» в yt-dlp.
    return f"ytsearch{limit}:{query} #shorts"


def normalize_source(source: str, limit: int) -> str:
    """Превратить запрос пользователя в URL, понятный yt-dlp.

    - «текстовый запрос»          -> поиск по YouTube Shorts
    - готовый http(s)-URL         -> как есть (страница хэштега TikTok, канал, Reels…)
    """
    if source.startswith("http://") or source.startswith("https://"):
        return source
    return _yt_search_url(source, limit)


def _extract_entries(url: str, limit: int) -> Iterable[dict[str, Any]]:
    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": "in_playlist",  # быстро: не лезем в каждый ролик отдельно
        "playlistend": limit,
        "ignoreerrors": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        return []
    entries = info.get("entries") if "entries" in info else [info]
    return [e for e in entries if e]


def _platform_of(entry: dict) -> str:
    extractor = (entry.get("ie_key") or entry.get("extractor") or "").lower()
    if "tiktok" in extractor:
        return "tiktok"
    if "instagram" in extractor:
        return "instagram"
    if "youtube" in extractor:
        return "youtube"
    return extractor or "unknown"


def discover(sources: list[str], limit: int = 20) -> list[int]:
    """Найти ролики по списку источников. Возвращает id записей в БД."""
    found: list[int] = []
    for source in sources:
        url = normalize_source(source, limit)
        print(f"[discover] источник: {source} -> {url}")
        for entry in _extract_entries(url, limit):
            meta = {
                "url": entry.get("url") or entry.get("webpage_url"),
                "platform": _platform_of(entry),
                "title": entry.get("title"),
                "author": entry.get("uploader") or entry.get("channel"),
                "views": entry.get("view_count"),
                "likes": entry.get("like_count"),
                "comments": entry.get("comment_count"),
                "duration": entry.get("duration"),
            }
            if not meta["url"]:
                continue
            vid = db.upsert_discovered(meta)
            found.append(vid)
            print(f"  + [{vid}] {meta['platform']}: {meta['title'] or meta['url']}")
    print(f"[discover] всего найдено/обновлено: {len(found)}")
    return found
