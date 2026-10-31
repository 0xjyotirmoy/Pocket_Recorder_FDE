"""Audio helpers. ffmpeg comes from PATH or the pip-installed imageio-ffmpeg binary, so there is
nothing to install by hand on Windows."""
import shutil
import subprocess
import wave
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def ffmpeg(args: list[str]) -> None:
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg not available (pip install imageio-ffmpeg)")
    res = subprocess.run([exe, "-y", "-v", "error", *args], capture_output=True, text=True, timeout=1800)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {res.stderr.strip()[:300]}")


def is_wav(path: Path) -> bool:
    with open(path, "rb") as f:
        head = f.read(12)
    return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE"


def wav_duration(path: Path) -> float | None:
    """Duration in seconds. Raises ValueError if the file is not a WAV; None if unknown."""
    if not is_wav(path):
        raise ValueError("not a WAV file (missing RIFF/WAVE header)")
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate()
            if rate <= 0:
                raise ValueError("bad sample rate")
            return w.getnframes() / rate
    except (wave.Error, EOFError, ValueError):
        return ffprobe_duration(path)


def ffprobe_duration(path: Path) -> float | None:
    """Duration without ffprobe: decode with ffmpeg and read the reported time."""
    exe = ffmpeg_exe()
    if not exe:
        return None
    try:
        res = subprocess.run([exe, "-v", "error", "-i", str(path), "-f", "null", "-", "-stats"],
                             capture_output=True, text=True, timeout=300)
        import re

        times = re.findall(r"time=(\d+):(\d+):(\d+\.?\d*)", res.stderr)
        if times:
            h, m, s = times[-1]
            return int(h) * 3600 + int(m) * 60 + float(s)
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def to_wav16k(src: Path, dest: Path) -> float:
    """Convert any audio (mp3, m4a, ogg, aac, webm, phone recordings) to 16 kHz mono 16-bit WAV,
    the same format the recorder sends. Returns duration in seconds."""
    ffmpeg(["-i", str(src), "-vn", "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", str(dest)])
    dur = wav_duration(dest)
    if not dur or dur <= 0:
        raise ValueError("file contains no audio")
    return dur
