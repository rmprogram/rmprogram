"""Transcripción y subtítulos automáticos con Whisper LOCAL (faster-whisper).

El modelo se descarga una sola vez (~75 MB 'tiny', ~145 MB 'base') y después
funciona sin internet, sin API y sin coste por uso. Usa int8 en CPU para ser ligero.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from ..core.ffmpeg_utils import extract_audio_pcm

MODELS = ["tiny", "base", "small", "medium"]

FILLERS_ES = {"eh", "ehh", "em", "emm", "mm", "mmm", "este", "ah", "ahh", "um", "uh", "pues", "bueno"}
FILLERS_EN = {"um", "uh", "uhm", "erm", "hmm", "like"}

_model_cache: dict[str, object] = {}


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word]


def is_available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def _get_model(size: str):
    if size not in _model_cache:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Para subtítulos automáticos instala el módulo opcional:\n"
                "    pip install faster-whisper\n"
                "(Funciona 100% local, sin API ni tokens.)"
            ) from exc
        _model_cache[size] = WhisperModel(size, device="auto", compute_type="int8")
    return _model_cache[size]


def transcribe(path: str, start: float = 0.0, end: float = 0.0, model: str = "base",
               language: Optional[str] = None, progress: Optional[Callable[[float], None]] = None,
               cancel: Optional[Callable[[], bool]] = None) -> list[Segment]:
    """Transcribe el rango [start, end] del archivo. Tiempos devueltos en tiempo de fuente."""
    audio = extract_audio_pcm(path, start, (end - start) if end > start else 0.0, rate=16000)
    total = max(audio.size / 16000, 1e-6)
    m = _get_model(model)
    segments, _info = m.transcribe(
        audio, language=language or None, vad_filter=True, word_timestamps=True, beam_size=1,
    )
    out: list[Segment] = []
    for seg in segments:
        if cancel and cancel():
            break
        words = [Word(w.start + start, w.end + start, w.word.strip()) for w in (seg.words or [])]
        out.append(Segment(seg.start + start, seg.end + start, seg.text.strip(), words))
        if progress:
            progress(min(1.0, seg.end / total))
    return out


def to_caption_chunks(segments: list[Segment], max_words: int = 6, max_dur: float = 3.0) -> list[tuple[float, float, str]]:
    """Agrupa palabras en subtítulos cortos y dinámicos (estilo redes sociales)."""
    chunks: list[tuple[float, float, str]] = []
    for seg in segments:
        if not seg.words:
            chunks.append((seg.start, seg.end, seg.text))
            continue
        buf: list[Word] = []
        for w in seg.words:
            buf.append(w)
            if len(buf) >= max_words or (buf[-1].end - buf[0].start) >= max_dur or w.text.endswith((".", "?", "!", ",")):
                chunks.append((buf[0].start, buf[-1].end, " ".join(x.text for x in buf)))
                buf = []
        if buf:
            chunks.append((buf[0].start, buf[-1].end, " ".join(x.text for x in buf)))
    return chunks


def filler_ranges(segments: list[Segment], fillers: Optional[set[str]] = None) -> list[tuple[float, float]]:
    """Intervalos (tiempo de fuente) ocupados por muletillas como 'eh', 'este', 'um'."""
    fillers = fillers or (FILLERS_ES | FILLERS_EN)
    out = []
    for seg in segments:
        for w in seg.words:
            token = re.sub(r"[^\wáéíóúñü]", "", w.text.lower())
            if token in fillers:
                out.append((w.start, w.end))
    return out
