#!/usr/bin/env python3
"""Офлайн-демо стадии generate: собирает вертикальное видео из тестового сценария
тем же кодом сборки, что и боевой пайплайн (pipeline.generate.assemble_video).

Ничего не качает и не ходит в API:
  - сценарий задан вручную (как его выдал бы Claude по шаблону хука);
  - фон рисуется ffmpeg'ом (анимированный градиент);
  - озвучка — офлайн через espeak-ng (если установлен), иначе тишина.

Запуск:  python tools/demo.py
Результат:  data/outputs/demo_final.mp4
"""
import shutil
import subprocess
import sys
from pathlib import Path

# чтобы импортировался пакет pipeline из корня репозитория
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline import ffmpeg_utils, generate

# --- Тестовый сценарий (хук «личный эксперимент за N дней») ---
SCENARIO = {
    "title": "Я кодил на Python каждый день 30 дней — вот что вышло",
    "segments": [
        "Я писал код на Python каждый день целый месяц.",
        "Первая неделя — сплошные ошибки и отчаяние.",
        "Потом дошло: учить надо не синтаксис, а решать задачи.",
        "На день двадцатый я собрал своего первого телеграм-бота.",
        "К тридцатому — уже автоматизировал свою рутину на работе.",
        "Главный вывод: дело не в таланте, а в ежедневной практике.",
        "Хочешь так же? Забирай мой план в закрепе.",
    ],
    "hashtags": ["#python", "#обучение", "#кодинг"],
}


def make_background(dst: Path) -> Path:
    """Нарисовать анимированный градиент 1080x1920 — фон для демо."""
    ffmpeg_utils.run([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "gradients=s=1080x1920:c0=0x10243f:c1=0x3a1052:"
              "x0=0:y0=0:x1=1080:y1=1920:type=linear:speed=0.015:duration=30:rate=30",
        "-t", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dst),
    ])
    return dst


def _find_piper_model() -> str:
    """Найти .onnx модель Piper: из PIPER_MODEL или из ./assets/voices/*.onnx."""
    if config.PIPER_MODEL and Path(config.PIPER_MODEL).exists():
        return config.PIPER_MODEL
    voices = sorted(Path("assets/voices").glob("*.onnx")) if Path("assets/voices").exists() else []
    return str(voices[0]) if voices else ""


def make_voice(text: str, dst: Path) -> Path:
    """Озвучка офлайн: сначала Piper (нейроголос), потом espeak-ng, потом тишина."""
    model = _find_piper_model()
    if model and shutil.which("piper"):
        subprocess.run(
            ["piper", "--model", model, "--output_file", str(dst)],
            input=text.encode("utf-8"), check=True,
        )
    elif shutil.which("espeak-ng"):
        print("[demo] Piper-модель не найдена — озвучка через espeak-ng (роботизированно)")
        subprocess.run(
            ["espeak-ng", "-v", "ru", "-s", "155", "-p", "45", "-a", "190",
             "-w", str(dst), text],
            check=True,
        )
    else:
        print("[demo] espeak-ng не найден — кладу тишину вместо озвучки")
        words = max(len(text.split()), 1)
        seconds = max(8, words / 2.5)  # ~150 слов/мин
        ffmpeg_utils.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=r=24000:cl=mono", "-t", str(seconds), str(dst),
        ])
    return dst


def main() -> Path:
    ffmpeg_utils.ensure_ffmpeg()
    config.ensure_dirs()

    bg = make_background(config.OUTPUTS_DIR / "demo_bg.mp4")
    voice = make_voice(" ".join(SCENARIO["segments"]), config.OUTPUTS_DIR / "demo_voice.wav")
    out = config.OUTPUTS_DIR / "demo_final.mp4"

    generate.assemble_video(SCENARIO["segments"], voice, bg, out)

    print(f"\n[demo] Сценарий:  {SCENARIO['title']}")
    print(f"[demo] Хэштеги:   {' '.join(SCENARIO['hashtags'])}")
    print(f"[demo] Готово ->  {out}")
    return out


if __name__ == "__main__":
    main()
