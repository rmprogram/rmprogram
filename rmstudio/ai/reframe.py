"""Reencuadre inteligente para formato vertical: centra el encuadre en las caras.

Usa el detector de caras clásico de OpenCV (incluido, sin descargas ni GPU)
analizando pocos fotogramas reducidos, así que es muy rápido.
"""
from __future__ import annotations

import subprocess
from typing import Optional

import numpy as np

from ..core.ffmpeg_utils import _CREATE_NO_WINDOW, ffmpeg_bin


def _grab_frames(path: str, start: float, end: float, samples: int, width: int = 320) -> list[np.ndarray]:
    frames = []
    length = max(end - start, 0.1)
    for k in range(samples):
        t = start + length * (k + 0.5) / samples
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", path,
               "-frames:v", "1", "-vf", f"scale={width}:-2,format=gray", "-f", "rawvideo", "pipe:1"]
        res = subprocess.run(cmd, capture_output=True, creationflags=_CREATE_NO_WINDOW)
        data = res.stdout
        if res.returncode == 0 and data and len(data) % width == 0:
            frames.append(np.frombuffer(data, dtype=np.uint8).reshape(-1, width))
    return frames


def face_center_x(path: str, start: float, end: float, samples: int = 8) -> Optional[float]:
    """Centro horizontal normalizado (0..1) de las caras detectadas, o None si no hay."""
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV 5 lo movió a contrib
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    xs, weights = [], []
    for img in _grab_frames(path, start, end, samples):
        faces = cascade.detectMultiScale(img, scaleFactor=1.15, minNeighbors=5, minSize=(24, 24))
        w_img = img.shape[1]
        for (x, _y, w, h) in faces:
            xs.append((x + w / 2) / w_img)
            weights.append(w * h)  # caras más grandes = más importantes
    if not xs:
        return None
    order = np.argsort(xs)
    xs_s, w_s = np.array(xs)[order], np.array(weights, dtype=float)[order]
    cum = np.cumsum(w_s)
    return float(xs_s[np.searchsorted(cum, cum[-1] / 2)])  # mediana ponderada


def crop_offset_for(center_x: float, src_w: int, src_h: int, dst_w: int, dst_h: int) -> float:
    """Convierte el centro deseado en el parámetro de recorte (0..1) que usa el exportador."""
    scale = max(dst_w / src_w, dst_h / src_h)
    scaled_w = src_w * scale
    extra = scaled_w - dst_w
    if extra <= 1:
        return 0.5
    left = center_x * scaled_w - dst_w / 2
    return float(np.clip(left / extra, 0.0, 1.0))
