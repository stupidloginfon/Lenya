"""Тонкие обёртки над ffmpeg / ffprobe (системные бинарники)."""
import json
import shutil
import subprocess
from pathlib import Path


def ensure_ffmpeg() -> None:
    for bin_ in ("ffmpeg", "ffprobe"):
        if shutil.which(bin_) is None:
            raise RuntimeError(
                f"Не найден {bin_}. Установи ffmpeg (см. README, раздел «Что нужно»)."
            )


def run(cmd: list[str]) -> None:
    """Запустить ffmpeg-команду, показав внятную ошибку при падении."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg упал ({proc.returncode}):\n{' '.join(cmd)}\n\n{proc.stderr[-2000:]}"
        )


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", str(path)]
    )
    return float(json.loads(out)["format"]["duration"])


def extract_clip(src: Path, dst: Path, start: float, duration: float) -> Path:
    """Вырезать фрагмент [start, start+duration)."""
    run([
        "ffmpeg", "-y", "-ss", str(start), "-i", str(src),
        "-t", str(duration), "-c:v", "libx264", "-c:a", "aac",
        "-pix_fmt", "yuv420p", str(dst),
    ])
    return dst


def extract_audio(src: Path, dst: Path) -> Path:
    """Достать аудиодорожку в wav 16кГц (для Whisper)."""
    run([
        "ffmpeg", "-y", "-i", str(src), "-vn",
        "-ac", "1", "-ar", "16000", str(dst),
    ])
    return dst
