"""Detección de cambios de escena (local, analiza a baja resolución para ir rápido)."""
from __future__ import annotations

import re

from ..core.ffmpeg_utils import CancelCb, ProgressCb, run_ffmpeg

_PTS = re.compile(r"pts_time:\s*([\d.]+)")


def detect_scenes(path: str, start: float = 0.0, end: float = 0.0, threshold: float = 0.35,
                  min_gap: float = 1.0, progress: ProgressCb = None,
                  cancel: CancelCb = None) -> list[float]:
    """Devuelve los instantes (tiempo de fuente) donde cambia la escena."""
    args = []
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    length = (end - start) if end > start else 0.0
    if length > 0:
        args += ["-t", f"{length:.3f}"]
    # Escalar a 160 px de ancho reduce muchísimo el coste de CPU.
    args += ["-i", path, "-an", "-sn",
             "-vf", f"scale=160:-2,select='gt(scene,{threshold})',showinfo",
             "-f", "null", "-"]
    log = run_ffmpeg(args, duration=length, progress=progress, cancel=cancel)
    cuts: list[float] = []
    for line in log.splitlines():
        if "showinfo" not in line:
            continue
        m = _PTS.search(line)
        if m:
            t = float(m.group(1)) + start
            if not cuts or t - cuts[-1] >= min_gap:
                cuts.append(t)
    return cuts


def ranges_from_cuts(start: float, end: float, cuts: list[float], min_len: float = 0.5) -> list[tuple[float, float]]:
    points = [start] + [c for c in cuts if start + min_len < c < end - min_len] + [end]
    return [(a, b) for a, b in zip(points, points[1:]) if b - a >= 0.05]
