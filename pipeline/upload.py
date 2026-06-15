"""Загрузка готового видео на площадки.

YouTube Shorts — полноценная реализация (есть открытый Data API v3).
TikTok и Instagram — заготовки: их API закрытые и требуют одобренного
dev-приложения и бизнес-аккаунта. Точки подключения и официальные шаги описаны
в комментариях и в README.
"""
import json
from pathlib import Path

import config
from pipeline import db


def _meta(row) -> dict:
    data = json.loads(row["analysis_json"]) if row["analysis_json"] else {}
    gen = data.get("generated", {})
    title = gen.get("title") or row["title"] or "Видео"
    hashtags = gen.get("hashtags", [])
    description = title + ("\n\n" + " ".join(hashtags) if hashtags else "")
    return {"title": title[:100], "description": description, "tags": [h.lstrip("#") for h in hashtags]}


# ---------------------------------------------------------------- YouTube ----
def upload_youtube(video_id: int) -> str:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    token_path = Path("youtube.token.json")

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                config.YOUTUBE_CLIENT_SECRET, scopes
            )
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    row = db.get(video_id)
    meta = _meta(row)
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": "22",
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(row["output_path"], chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    url = f"https://youtube.com/shorts/{response['id']}"
    db.mark_uploaded(video_id, "youtube", url)
    print(f"[upload] YouTube -> {url}")
    return url


# ----------------------------------------------------------------- TikTok ----
def upload_tiktok(video_id: int) -> str:
    """Заготовка под TikTok Content Posting API (direct post).

    Что нужно:
      1. Зарегистрировать приложение на developers.tiktok.com и пройти ревью на
         scope `video.publish`.
      2. Получить user access token (OAuth).
      3. Init -> загрузка файла -> публикация (см. docs Content Posting API).
    """
    if not config.TIKTOK_ACCESS_TOKEN:
        raise RuntimeError("TIKTOK_ACCESS_TOKEN не задан — нужен одобренный доступ к API")
    # import requests
    # row = db.get(video_id)
    # 1) POST https://open.tiktokapis.com/v2/post/publish/video/init/
    #    headers: Authorization: Bearer <token>
    #    body: {post_info: {...}, source_info: {source: "FILE_UPLOAD", video_size, chunk_size, total_chunk_count}}
    # 2) PUT upload_url (из ответа) — заливаем байты файла row["output_path"]
    # 3) Статус через /v2/post/publish/status/fetch/
    raise NotImplementedError(
        "TikTok-загрузка не реализована: нужен одобренный Content Posting API. "
        "Точки подключения — в комментариях этой функции и в README."
    )


# -------------------------------------------------------------- Instagram ----
def upload_instagram(video_id: int) -> str:
    """Заготовка под Instagram Reels (Graph API).

    Что нужно:
      1. Бизнес/креатор-аккаунт, связанный с Facebook-страницей.
      2. Долгоживущий access token и IG_USER_ID.
      3. Видео должно быть доступно по ПУБЛИЧНОМУ URL — Instagram скачивает его сам
         (т.е. сначала залей файл на свой хостинг/S3).
    """
    if not (config.IG_ACCESS_TOKEN and config.IG_USER_ID):
        raise RuntimeError("IG_ACCESS_TOKEN / IG_USER_ID не заданы")
    # import requests, time
    # 1) POST graph.facebook.com/v21.0/{IG_USER_ID}/media
    #    params: media_type=REELS, video_url=<публичный URL>, caption=..., access_token=...
    #    -> {id: creation_id}
    # 2) ждём, пока статус контейнера станет FINISHED
    #    GET /{creation_id}?fields=status_code
    # 3) POST /{IG_USER_ID}/media_publish?creation_id=...&access_token=...
    raise NotImplementedError(
        "Instagram-загрузка не реализована: нужен Graph API и публичный URL файла. "
        "Точки подключения — в комментариях этой функции и в README."
    )


_PLATFORMS = {
    "youtube": upload_youtube,
    "tiktok": upload_tiktok,
    "instagram": upload_instagram,
}


def upload(video_id: int, platforms: list[str]) -> dict[str, str]:
    results = {}
    for p in platforms:
        fn = _PLATFORMS.get(p)
        if not fn:
            print(f"[upload] неизвестная площадка: {p}")
            continue
        try:
            results[p] = fn(video_id)
        except Exception as e:  # noqa: BLE001 — не валим весь прогон из-за одной площадки
            print(f"[upload] {p}: ошибка — {e}")
    return results
