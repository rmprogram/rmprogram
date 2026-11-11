"""Modelo del proyecto: clips en la línea de tiempo, subtítulos y deshacer/rehacer."""
from __future__ import annotations

import copy
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

MIN_CLIP = 0.05  # segundos


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Clip:
    source: str
    start: float          # inicio dentro del archivo fuente (s)
    end: float            # fin dentro del archivo fuente (s)
    speed: float = 1.0
    volume: float = 1.0
    label: str = ""
    crop_x: Optional[float] = None  # centro horizontal (0..1) para reencuadre; None = centro
    id: str = field(default_factory=_new_id)

    @property
    def src_length(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def duration(self) -> float:
        """Duración en la línea de tiempo (afectada por la velocidad)."""
        return self.src_length / max(self.speed, 0.01)


@dataclass
class Subtitle:
    start: float  # tiempo en la línea de tiempo
    end: float
    text: str


@dataclass
class Project:
    clips: list[Clip] = field(default_factory=list)
    subtitles: list[Subtitle] = field(default_factory=list)
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    path: Optional[str] = None

    def __post_init__(self):
        self._undo: list[dict] = []
        self._redo: list[dict] = []

    # ------------------------------------------------------------------ historial
    def snapshot(self) -> None:
        """Guarda el estado actual antes de una modificación."""
        self._undo.append(self._state())
        if len(self._undo) > 100:
            self._undo.pop(0)
        self._redo.clear()

    def _state(self) -> dict:
        return {
            "clips": [asdict(c) for c in self.clips],
            "subtitles": [asdict(s) for s in self.subtitles],
        }

    def _restore(self, st: dict) -> None:
        self.clips = [Clip(**c) for c in st["clips"]]
        self.subtitles = [Subtitle(**s) for s in st["subtitles"]]

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._state())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._state())
        self._restore(self._redo.pop())
        return True

    # ------------------------------------------------------------------ consultas
    @property
    def duration(self) -> float:
        return sum(c.duration for c in self.clips)

    def clip_start(self, index: int) -> float:
        return sum(c.duration for c in self.clips[:index])

    def index_of(self, clip_id: str) -> int:
        for i, c in enumerate(self.clips):
            if c.id == clip_id:
                return i
        return -1

    def locate(self, t: float) -> tuple[int, float]:
        """Devuelve (índice del clip, desplazamiento en la línea de tiempo dentro del clip)."""
        if not self.clips:
            return -1, 0.0
        acc = 0.0
        for i, c in enumerate(self.clips):
            if t < acc + c.duration or i == len(self.clips) - 1:
                return i, min(max(0.0, t - acc), c.duration)
            acc += c.duration
        return len(self.clips) - 1, self.clips[-1].duration

    def source_time(self, t: float) -> tuple[int, float]:
        """Traduce tiempo de la línea de tiempo a (índice, tiempo en el archivo fuente)."""
        i, off = self.locate(t)
        if i < 0:
            return -1, 0.0
        c = self.clips[i]
        return i, c.start + off * c.speed

    # ------------------------------------------------------------------ edición
    def add_clip(self, source: str, start: float, end: float, index: Optional[int] = None, label: str = "") -> Clip:
        clip = Clip(source=source, start=start, end=end, label=label)
        if index is None:
            self.clips.append(clip)
        else:
            self.clips.insert(index, clip)
        return clip

    def remove_clip(self, index: int) -> None:
        if 0 <= index < len(self.clips):
            removed = self.clips.pop(index)
            self._shift_subtitles_after_removal(index, removed)

    def _shift_subtitles_after_removal(self, index: int, removed: Clip) -> None:
        t0 = self.clip_start(index)
        t1 = t0 + removed.duration
        self.subtitles = _cut_subtitles(self.subtitles, t0, t1)

    def move_clip(self, src: int, dst: int) -> None:
        if src == dst or not (0 <= src < len(self.clips)):
            return
        clip = self.clips.pop(src)
        dst = max(0, min(dst, len(self.clips)))
        self.clips.insert(dst, clip)

    def split_at(self, t: float) -> bool:
        i, off = self.locate(t)
        if i < 0:
            return False
        c = self.clips[i]
        src_cut = c.start + off * c.speed
        if src_cut - c.start < MIN_CLIP or c.end - src_cut < MIN_CLIP:
            return False
        second = copy.deepcopy(c)
        second.id = _new_id()
        second.start = src_cut
        c.end = src_cut
        self.clips.insert(i + 1, second)
        return True

    def trim(self, index: int, start: Optional[float] = None, end: Optional[float] = None,
             source_duration: Optional[float] = None) -> None:
        c = self.clips[index]
        if start is not None:
            c.start = max(0.0, min(start, c.end - MIN_CLIP))
        if end is not None:
            hi = source_duration if source_duration else end
            c.end = max(c.start + MIN_CLIP, min(end, hi))

    def replace_clip(self, index: int, new_clips: list[Clip]) -> None:
        """Sustituye un clip por varios (p. ej. tras cortar silencios)."""
        self.clips[index:index + 1] = new_clips

    def split_clip_into_ranges(self, index: int, ranges: list[tuple[float, float]]) -> int:
        """Reemplaza el clip por sub-clips que cubren `ranges` (tiempos de fuente). Devuelve nº de clips."""
        c = self.clips[index]
        pieces = []
        for s, e in ranges:
            s, e = max(s, c.start), min(e, c.end)
            if e - s >= MIN_CLIP:
                p = copy.deepcopy(c)
                p.id = _new_id()
                p.start, p.end = s, e
                pieces.append(p)
        if pieces:
            self.replace_clip(index, pieces)
        return len(pieces)

    # ------------------------------------------------------------------ archivo
    def to_dict(self) -> dict:
        return {
            "version": 1,
            "width": self.width, "height": self.height, "fps": self.fps,
            **self._state(),
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
        self.path = path

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        p = cls(width=data.get("width", 1920), height=data.get("height", 1080), fps=data.get("fps", 30.0))
        p._restore(data)
        p.path = path
        return p


def _cut_subtitles(subs: list[Subtitle], t0: float, t1: float) -> list[Subtitle]:
    """Elimina el intervalo [t0, t1] de la pista de subtítulos y desplaza los posteriores."""
    gap = t1 - t0
    out = []
    for s in subs:
        if s.end <= t0:
            out.append(s)
        elif s.start >= t1:
            out.append(Subtitle(s.start - gap, s.end - gap, s.text))
        else:
            ns = min(s.start, t0)
            ne = max(t0, s.end - gap)
            if ne - ns > 0.2:
                out.append(Subtitle(ns, ne, s.text))
    return out


def subtitles_to_srt(subs: list[Subtitle]) -> str:
    def ts(t: float) -> str:
        t = max(0.0, t)
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for n, s in enumerate(sorted(subs, key=lambda x: x.start), 1):
        lines += [str(n), f"{ts(s.start)} --> {ts(s.end)}", s.text.strip(), ""]
    return "\n".join(lines)
