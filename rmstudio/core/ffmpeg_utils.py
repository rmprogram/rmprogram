"""Utilidades para invocar FFmpeg/FFprobe de forma eficiente y con progreso."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

ProgressCb = Optional[Callable[[float], None]]
CancelCb = Optional[Callable[[], bool]]

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class FFmpegError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


def _find_binary(name: str) -> str:
    env = os.environ.get(f"RMSTUDIO_{name.upper()}")
    if env and os.path.exists(env):
        return env
    found = shutil.which(name)
    if found:
        return found
    if name == "ffmpeg":
        try:  # binario portable opcional (pip install imageio-ffmpeg)
            import imageio_ffmpeg  # type: ignore

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    raise FFmpegError(
        f"No se encontró '{name}'. Instala FFmpeg y agrégalo al PATH "
        f"(o define la variable RMSTUDIO_{name.upper()})."
    )


def ffmpeg_bin() -> str:
    return _find_binary("ffmpeg")


def ffprobe_bin() -> str:
    return _find_binary("ffprobe")


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 30.0
    has_video: bool = False
    has_audio: bool = False


def _parse_rate(rate: str) -> float:
    try:
        if "/" in rate:
            num, den = rate.split("/")
            return float(num) / float(den) if float(den) else 0.0
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: str) -> MediaInfo:
    cmd = [
        ffprobe_bin(), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, creationflags=_CREATE_NO_WINDOW)
    if res.returncode != 0:
        raise FFmpegError(f"No se pudo leer el archivo: {path}\n{res.stderr.strip()}")
    data = json.loads(res.stdout or "{}")
    info = MediaInfo(path=path, duration=float(data.get("format", {}).get("duration", 0) or 0))
    for st in data.get("streams", []):
        kind = st.get("codec_type")
        if kind == "video" and not info.has_video and st.get("disposition", {}).get("attached_pic", 0) == 0:
            info.has_video = True
            info.width = int(st.get("width", 0))
            info.height = int(st.get("height", 0))
            info.fps = _parse_rate(st.get("avg_frame_rate", "0")) or _parse_rate(st.get("r_frame_rate", "30")) or 30.0
            if not info.duration:
                info.duration = float(st.get("duration", 0) or 0)
        elif kind == "audio":
            info.has_audio = True
            if not info.duration:
                info.duration = float(st.get("duration", 0) or 0)
    return info


_TIME_RE = re.compile(r"out_time_(?:us|ms)=(\d+)")


def run_ffmpeg(
    args: Sequence[str],
    duration: float = 0.0,
    progress: ProgressCb = None,
    cancel: CancelCb = None,
    cwd: Optional[str] = None,
) -> str:
    """Ejecuta ffmpeg con `args` y devuelve el stderr completo.

    Si se indica `duration`, se reporta el progreso (0..1) mediante `progress`.
    """
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", cwd=cwd, creationflags=_CREATE_NO_WINDOW,
    )
    err_chunks: list[str] = []

    def _drain():
        assert proc.stderr is not None
        for line in proc.stderr:
            err_chunks.append(line)

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        if cancel and cancel():
            proc.kill()
            proc.wait()
            raise Cancelled("Operación cancelada")
        m = _TIME_RE.search(line)
        if m and duration > 0 and progress:
            seconds = int(m.group(1)) / 1_000_000
            progress(max(0.0, min(1.0, seconds / duration)))
    proc.wait()
    t.join(timeout=5)
    stderr = "".join(err_chunks)
    if proc.returncode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"FFmpeg falló (código {proc.returncode}):\n{tail}")
    if progress:
        progress(1.0)
    return stderr


def extract_audio_pcm(path: str, start: float = 0.0, duration: float = 0.0, rate: int = 16000):
    """Decodifica el audio a PCM mono float32 (numpy) a la frecuencia indicada."""
    import numpy as np

    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    if duration > 0:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-i", path, "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "pipe:1"]
    res = subprocess.run(cmd, capture_output=True, creationflags=_CREATE_NO_WINDOW)
    if res.returncode != 0:
        raise FFmpegError(res.stderr.decode("utf-8", "replace")[-800:])
    return np.frombuffer(res.stdout, dtype=np.float32)


def make_thumbnail(path: str, out_png: str, at: float = 1.0, width: int = 240) -> bool:
    cmd = [
        ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y",
        "-ss", f"{max(0.0, at):.2f}", "-i", path, "-frames:v", "1",
        "-vf", f"scale={width}:-2", out_png,
    ]
    res = subprocess.run(cmd, capture_output=True, creationflags=_CREATE_NO_WINDOW)
    return res.returncode == 0 and os.path.exists(out_png)


def fmt_time(seconds: float, ms: bool = True) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if ms:
        return f"{h:02d}:{m:02d}:{s:06.3f}" if h else f"{m:02d}:{s:06.3f}"
    return f"{h:02d}:{m:02d}:{int(s):02d}" if h else f"{m:02d}:{int(s):02d}"
