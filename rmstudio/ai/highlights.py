"""Búsqueda de "mejores momentos" para crear clips cortos (Shorts/Reels/TikTok).

Combina energía de audio (risas, emoción, música alta), densidad de voz y cambios
de escena. Todo con numpy sobre audio a 8 kHz: segundos de cálculo, 0 tokens.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..core.ffmpeg_utils import extract_audio_pcm

RATE = 8000
HOP = 0.25  # segundos por ventana


@dataclass
class Highlight:
    start: float
    end: float
    score: float  # 0..100


def audio_envelope(path: str, start: float = 0.0, end: float = 0.0) -> np.ndarray:
    pcm = extract_audio_pcm(path, start, (end - start) if end > start else 0.0, rate=RATE)
    win = int(RATE * HOP)
    if pcm.size < win:
        return np.zeros(1, dtype=np.float32)
    n = pcm.size // win
    frames = pcm[: n * win].reshape(n, win)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)  # dBFS


def score_curve(env_db: np.ndarray, scene_cuts_rel: Optional[list[float]] = None) -> np.ndarray:
    if env_db.size == 0:
        return env_db
    # Normalizamos con percentiles para ser robustos a ruido de fondo.
    lo, hi = np.percentile(env_db, 10), np.percentile(env_db, 98)
    loud = np.clip((env_db - lo) / max(hi - lo, 1e-6), 0, 1)
    # Voz activa: ventanas por encima del umbral relativo.
    voice = (env_db > lo + 0.35 * (hi - lo)).astype(np.float32)
    # Picos repentinos (sorpresa, risa, golpe).
    diff = np.clip(np.diff(env_db, prepend=env_db[0]), 0, None)
    spikes = np.clip(diff / (np.percentile(diff, 99) + 1e-6), 0, 1)
    score = 0.5 * loud + 0.3 * voice + 0.2 * spikes
    if scene_cuts_rel:
        cuts = np.zeros_like(score)
        for t in scene_cuts_rel:
            k = int(t / HOP)
            if 0 <= k < cuts.size:
                cuts[k] = 1.0
        score = score + 0.15 * cuts
    return score


def find_highlights(path: str, duration: float, clip_len: float = 30.0, count: int = 3,
                    start: float = 0.0, end: float = 0.0,
                    scene_cuts: Optional[list[float]] = None) -> list[Highlight]:
    end = end if end > start else duration
    env = audio_envelope(path, start, end)
    rel_cuts = [c - start for c in (scene_cuts or []) if start <= c <= end]
    sc = score_curve(env, rel_cuts)
    win = max(1, int(clip_len / HOP))
    if sc.size <= win:
        return [Highlight(start, end, 100.0)]
    sums = np.convolve(sc, np.ones(win), mode="valid")  # puntuación de cada ventana posible
    best = float(sums.max()) or 1.0
    chosen: list[Highlight] = []
    taken = np.zeros(sums.size, dtype=bool)
    order = np.argsort(sums)[::-1]
    for k in order:
        if len(chosen) >= count:
            break
        if taken[k]:
            continue
        s = start + k * HOP
        chosen.append(Highlight(float(s), float(min(s + clip_len, end)), round(100 * float(sums[k]) / best, 1)))
        lo, hi = max(0, k - win + 1), min(sums.size, k + win)
        taken[lo:hi] = True  # sin solapamientos
    # Ajustar el inicio a un momento con menos volumen (evita cortar a mitad de palabra).
    for h in chosen:
        k = int((h.start - start) / HOP)
        a, b = max(0, k - 4), min(env.size, k + 5)
        if b > a:
            k2 = a + int(np.argmin(env[a:b]))
            shift = (k2 - k) * HOP
            h.start = float(max(start, h.start + shift))
            h.end = float(min(end, h.end + shift))
    return sorted(chosen, key=lambda h: h.start)
