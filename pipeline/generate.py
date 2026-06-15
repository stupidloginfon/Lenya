"""Генерация нового ролика по шаблону залетевшего хука.

Шаги:
  1. Claude пишет сценарий под твою тему/продукт, используя шаблон хука исходника.
  2. edge-tts озвучивает сценарий (бесплатный нейроголос).
  3. ffmpeg собирает вертикальное видео: фон (b-roll или обрезанный исходник)
     + выжженные субтитры под длину озвучки.

Важно про авторские права: если b-roll не задан, фоном идёт обрезанный кусок
исходника — так делать можно только если у тебя есть на это права. Лучше класть
свои клипы в BROLL_DIR.
"""
import asyncio
import json
import random
from pathlib import Path

import anthropic
import edge_tts

import config
from pipeline import db, ffmpeg_utils

_SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Реплики по порядку: первая — хук, последняя — призыв к действию",
        },
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "segments", "hashtags"],
    "additionalProperties": False,
}


def _write_script(row, topic: str) -> dict:
    analysis = json.loads(row["analysis_json"]) if row["analysis_json"] else {}
    template = analysis.get("reusable_template", row["hook_text"] or "")
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2000,
        system=(
            "Ты — сценарист коротких вертикальных видео. По шаблону залетевшего хука "
            "пишешь новый оригинальный сценарий под заданную тему. Пиши живо, разговорно, "
            "под озвучку. 5-9 коротких реплик, всего на 20-40 секунд. Не копируй исходник "
            "дословно — переноси только приём хука."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Шаблон хука: {template}\n"
                f"Почему он работает: {analysis.get('why_it_works', '')}\n\n"
                f"Тема/продукт для нового видео: {topic}\n\n"
                "Сделай сценарий по схеме."
            ),
        }],
        output_config={"format": {"type": "json_schema", "schema": _SCRIPT_SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


async def _tts(text: str, dst: Path) -> None:
    communicate = edge_tts.Communicate(text, config.TTS_VOICE)
    await communicate.save(str(dst))


def _make_srt(segments: list[str], total: float, dst: Path) -> None:
    """Раскидать реплики по таймлайну пропорционально длине текста."""
    lengths = [max(len(s), 1) for s in segments]
    total_len = sum(lengths)
    t = 0.0
    lines = []
    for i, (seg, ln) in enumerate(zip(segments, lengths), 1):
        dur = total * ln / total_len
        start, end = t, t + dur
        t = end
        lines.append(
            f"{i}\n{_ts(start)} --> {_ts(end)}\n{seg}\n"
        )
    dst.write_text("\n".join(lines), encoding="utf-8")


def _ts(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    ms = int((s - int(s)) * 1000)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"


def _pick_background(row) -> Path:
    """Фон для нового видео: случайный b-roll или обрезанный исходник."""
    brolls = list(config.BROLL_DIR.glob("*.mp4")) if config.BROLL_DIR.exists() else []
    if brolls:
        return random.choice(brolls)
    if row["download_path"] and Path(row["download_path"]).exists():
        print("[generate] b-roll не найден — использую исходник как фон "
              "(следи за авторскими правами!)")
        return Path(row["download_path"])
    raise RuntimeError("Нет фона: положи .mp4 в BROLL_DIR или скачай исходник")


def generate(video_id: int, topic: str) -> Path:
    """Сгенерировать новое видео. Возвращает путь к mp4."""
    ffmpeg_utils.ensure_ffmpeg()
    row = db.get(video_id)
    if row is None:
        raise ValueError(f"video {video_id} не найден")

    config.ensure_dirs()
    script = _write_script(row, topic)
    print(f"[generate] [{video_id}] сценарий: {script['title']}")

    narration = " ".join(script["segments"])
    voice_path = config.OUTPUTS_DIR / f"{video_id}_voice.mp3"
    asyncio.run(_tts(narration, voice_path))
    voice_dur = ffmpeg_utils.probe_duration(voice_path)

    srt_path = config.OUTPUTS_DIR / f"{video_id}.srt"
    _make_srt(script["segments"], voice_dur, srt_path)

    background = _pick_background(row)
    out_path = config.OUTPUTS_DIR / f"{video_id}_final.mp4"

    # Фон зацикливаем/обрезаем под длину озвучки, кадрируем в вертикаль 1080x1920,
    # выжигаем субтитры и подкладываем новую озвучку.
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"subtitles='{srt_path.as_posix()}':"
        "force_style='Alignment=2,FontSize=18,MarginV=120,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2'"
    )
    ffmpeg_utils.run([
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(background),
        "-i", str(voice_path),
        "-t", str(voice_dur),
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ])

    # Сохраним заголовок и хэштеги — пригодятся при загрузке.
    meta = {"title": script["title"], "hashtags": script["hashtags"]}
    db.update(
        video_id,
        output_path=str(out_path),
        status="generated",
        analysis_json=_merge_meta(row, meta),
    )
    print(f"[generate] [{video_id}] -> {out_path}")
    return out_path


def _merge_meta(row, extra: dict) -> str:
    base = json.loads(row["analysis_json"]) if row["analysis_json"] else {}
    base["generated"] = extra
    return json.dumps(base, ensure_ascii=False)
