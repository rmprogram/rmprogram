"""Detección de silencios (IA local basada en señal, 0 tokens) para corte automático."""
from __future__ import annotations

import re

from ..core.ffmpeg_utils import CancelCb, ProgressCb, run_ffmpeg

_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def detect_silences(path: str, start: float = 0.0, end: float = 0.0, noise_db: float = -35.0,
                    min_silence: float = 0.6, progress: ProgressCb = None,
                    cancel: CancelCb = None) -> list[tuple[float, float]]:
    """Devuelve intervalos de silencio en tiempo del archivo fuente."""
    args = []
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    length = (end - start) if end > start else 0.0
    if length > 0:
        args += ["-t", f"{length:.3f}"]
    args += ["-i", path, "-vn", "-sn", "-af",
             f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"]
    log = run_ffmpeg(args, duration=length, progress=progress, cancel=cancel)
    silences: list[tuple[float, float]] = []
    cur = None
    for line in log.splitlines():
        m = _START.search(line)
        if m:
            cur = max(0.0, float(m.group(1)))
            continue
        m = _END.search(line)
        if m and cur is not None:
            silences.append((cur + start, float(m.group(1)) + start))
            cur = None
    if cur is not None:  # silencio hasta el final
        silences.append((cur + start, end if end > start else cur + start))
    return silences


def keep_ranges(start: float, end: float, silences: list[tuple[float, float]],
                padding: float = 0.12, min_keep: float = 0.25) -> list[tuple[float, float]]:
    """Invierte los silencios para obtener los fragmentos con voz, con un margen natural."""
    ranges = []
    cursor = start
    for s, e in sorted(silences):
        s2, e2 = s + padding, e - padding
        if e2 <= s2:
            continue
        if s2 > cursor:
            ranges.append((cursor, min(s2, end)))
        cursor = max(cursor, e2)
    if cursor < end:
        ranges.append((cursor, end))
    merged: list[tuple[float, float]] = []
    for s, e in ranges:
        if e - s < min_keep:
            continue
        if merged and s - merged[-1][1] < 0.05:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged
