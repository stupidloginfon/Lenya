"""Лёгкое хранилище состояния пайплайна на SQLite.

Каждое видео проходит стадии: discovered → analyzed → generated → advertised → uploaded.
БД нужна, чтобы не обрабатывать один и тот же ролик дважды и видеть, что где застряло.
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import config


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url    TEXT UNIQUE NOT NULL,
            platform      TEXT,
            title         TEXT,
            author        TEXT,
            views         INTEGER,
            likes         INTEGER,
            comments      INTEGER,
            duration      REAL,
            download_path TEXT,
            hook_text     TEXT,
            hook_score    REAL,
            analysis_json TEXT,        -- разбор хука от Claude
            output_path   TEXT,        -- сгенерированное видео
            status        TEXT DEFAULT 'discovered',
            uploaded_to   TEXT,        -- json: {platform: url}
            created_at    REAL,
            updated_at    REAL
        )
        """
    )
    return conn


def upsert_discovered(meta: dict[str, Any]) -> int:
    """Добавить найденный ролик (или обновить метрики, если он уже есть)."""
    now = time.time()
    conn = connect()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO videos (source_url, platform, title, author, views, likes,
                                comments, duration, status, created_at, updated_at)
            VALUES (:url, :platform, :title, :author, :views, :likes,
                    :comments, :duration, 'discovered', :now, :now)
            ON CONFLICT(source_url) DO UPDATE SET
                views=excluded.views, likes=excluded.likes,
                comments=excluded.comments, updated_at=:now
            """,
            {
                "url": meta["url"],
                "platform": meta.get("platform"),
                "title": meta.get("title"),
                "author": meta.get("author"),
                "views": meta.get("views"),
                "likes": meta.get("likes"),
                "comments": meta.get("comments"),
                "duration": meta.get("duration"),
                "now": now,
            },
        )
        if cur.lastrowid:
            return cur.lastrowid
    row = conn.execute(
        "SELECT id FROM videos WHERE source_url = ?", (meta["url"],)
    ).fetchone()
    return row["id"]


def update(video_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn = connect()
    with conn:
        conn.execute(
            f"UPDATE videos SET {cols} WHERE id = ?", (*fields.values(), video_id)
        )


def get(video_id: int) -> Optional[sqlite3.Row]:
    return connect().execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()


def by_status(status: str) -> list[sqlite3.Row]:
    return connect().execute(
        "SELECT * FROM videos WHERE status = ? ORDER BY hook_score DESC NULLS LAST, id",
        (status,),
    ).fetchall()


def set_analysis(video_id: int, hook_text: str, score: float, analysis: dict) -> None:
    status = "analyzed" if score >= config.HOOK_SCORE_THRESHOLD else "rejected"
    update(
        video_id,
        hook_text=hook_text,
        hook_score=score,
        analysis_json=json.dumps(analysis, ensure_ascii=False),
        status=status,
    )


def mark_uploaded(video_id: int, platform: str, url: str) -> None:
    row = get(video_id)
    uploaded = json.loads(row["uploaded_to"]) if row and row["uploaded_to"] else {}
    uploaded[platform] = url
    update(video_id, uploaded_to=json.dumps(uploaded), status="uploaded")
