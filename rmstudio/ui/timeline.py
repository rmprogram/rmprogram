"""Línea de tiempo interactiva dibujada a mano (ligera y fluida)."""
from __future__ import annotations

import math
import os
from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ..core.ffmpeg_utils import fmt_time
from ..core.project import MIN_CLIP, Project
from . import theme

RULER_H = 26
VIDEO_Y = RULER_H + 8
VIDEO_H = 70
SUB_Y = VIDEO_Y + VIDEO_H + 8
SUB_H = 28
EDGE = 7
LEFT_PAD = 12


class Timeline(QWidget):
    seekRequested = Signal(float)
    selectionChanged = Signal(int)
    edited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Optional[Project] = None
        self.pps = 40.0           # píxeles por segundo
        self.scroll = 0.0         # segundos desplazados
        self.playhead = 0.0
        self.selected = -1
        self.thumbs: dict[str, QPixmap] = {}
        self.before_edit: Callable[[], None] = lambda: None
        self.source_duration: Callable[[str], float] = lambda p: 0.0
        self._drag: Optional[dict] = None
        self.setMinimumHeight(SUB_Y + SUB_H + 16)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # --------------------------------------------------------------- helpers
    def set_project(self, p: Project):
        self.project = p
        self.selected = -1
        self.update()

    def t2x(self, t: float) -> float:
        return LEFT_PAD + (t - self.scroll) * self.pps

    def x2t(self, x: float) -> float:
        return max(0.0, (x - LEFT_PAD) / self.pps + self.scroll)

    def clip_rects(self) -> list[QRectF]:
        rects, t = [], 0.0
        if not self.project:
            return rects
        for c in self.project.clips:
            rects.append(QRectF(self.t2x(t), VIDEO_Y, c.duration * self.pps, VIDEO_H))
            t += c.duration
        return rects

    def zoom_to_fit(self):
        if self.project and self.project.duration > 0:
            self.pps = max(2.0, (self.width() - 2 * LEFT_PAD) / self.project.duration)
            self.scroll = 0.0
            self.update()

    def set_playhead(self, t: float):
        self.playhead = t
        x = self.t2x(t)
        if x > self.width() - 40:  # seguir el cursor al reproducir
            self.scroll = t - (self.width() * 0.25) / self.pps
        elif x < 0:
            self.scroll = max(0.0, t - 1)
        self.update()

    def select(self, idx: int):
        self.selected = idx
        self.selectionChanged.emit(idx)
        self.update()

    # --------------------------------------------------------------- pintura
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.PANEL))
        self._paint_ruler(p, w)
        # pistas
        p.fillRect(QRectF(0, VIDEO_Y - 2, w, VIDEO_H + 4), QColor("#16161e"))
        p.fillRect(QRectF(0, SUB_Y - 2, w, SUB_H + 4), QColor("#16161e"))
        if not self.project or not self.project.clips:
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(0, VIDEO_Y, w, VIDEO_H), Qt.AlignCenter,
                       "Arrastra videos aquí o haz doble clic en la biblioteca para añadirlos")
        else:
            self._paint_clips(p)
            self._paint_subs(p)
        # cursor de reproducción
        x = self.t2x(self.playhead)
        p.setPen(QPen(QColor("#ff4d6d"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, h))
        path = QPainterPath()
        path.moveTo(x - 6, 0)
        path.lineTo(x + 6, 0)
        path.lineTo(x, 9)
        path.closeSubpath()
        p.fillPath(path, QColor("#ff4d6d"))
        p.end()

    def _paint_ruler(self, p: QPainter, w: int):
        p.fillRect(QRectF(0, 0, w, RULER_H), QColor(theme.PANEL_2))
        steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]
        step = next((s for s in steps if s * self.pps >= 70), 600)
        t = math.floor(self.scroll / step) * step
        end = self.x2t(w)
        p.setFont(QFont(p.font().family(), 8))
        while t <= end:
            x = self.t2x(t)
            p.setPen(QColor(theme.BORDER))
            p.drawLine(QPointF(x, RULER_H - 8), QPointF(x, RULER_H))
            p.setPen(QColor(theme.MUTED))
            p.drawText(QPointF(x + 3, RULER_H - 10), fmt_time(t, ms=step < 1))
            for k in range(1, 5):
                xs = self.t2x(t + step * k / 5)
                p.setPen(QColor(theme.BORDER))
                p.drawLine(QPointF(xs, RULER_H - 4), QPointF(xs, RULER_H))
            t += step

    def _paint_clips(self, p: QPainter):
        colors = {}
        for i, (c, r) in enumerate(zip(self.project.clips, self.clip_rects())):
            if r.right() < 0 or r.left() > self.width():
                continue
            col = colors.setdefault(c.source, QColor(theme.CLIP_COLORS[len(colors) % len(theme.CLIP_COLORS)]))
            body = r.adjusted(1, 0, -1, 0)
            path = QPainterPath()
            path.addRoundedRect(body, 6, 6)
            bg = QColor(col)
            bg.setAlpha(150)
            p.fillPath(path, bg)
            thumb = self.thumbs.get(c.source)
            if thumb and body.width() > 30:
                p.save()
                p.setClipPath(path)
                tw = thumb.width() * VIDEO_H / max(thumb.height(), 1)
                x = body.left()
                while x < body.right():  # tira de miniaturas
                    p.setOpacity(0.55)
                    p.drawPixmap(QRectF(x, body.top(), tw, VIDEO_H), thumb, QRectF(thumb.rect()))
                    x += tw * 2.2
                p.restore()
            pen = QPen(QColor("white") if i == self.selected else col.lighter(130), 2 if i == self.selected else 1)
            p.setPen(pen)
            p.drawPath(path)
            if body.width() > 40:
                p.setPen(QColor("white"))
                name = c.label or os.path.basename(c.source)
                extra = f"  ×{c.speed:g}" if abs(c.speed - 1) > 1e-3 else ""
                p.drawText(body.adjusted(8, 4, -6, 0), Qt.AlignTop | Qt.AlignLeft,
                           p.fontMetrics().elidedText(name + extra, Qt.ElideRight, int(body.width() - 14)))
                p.setPen(QColor(255, 255, 255, 170))
                p.drawText(body.adjusted(8, 0, -6, -4), Qt.AlignBottom | Qt.AlignLeft, fmt_time(c.duration))
        if self._drag and self._drag["mode"] == "move" and self._drag.get("drop") is not None:
            rects = self.clip_rects()
            d = self._drag["drop"]
            x = rects[d].left() if d < len(rects) else rects[-1].right()
            p.setPen(QPen(QColor(theme.ACCENT_2), 3))
            p.drawLine(QPointF(x, VIDEO_Y - 4), QPointF(x, VIDEO_Y + VIDEO_H + 4))

    def _paint_subs(self, p: QPainter):
        p.setFont(QFont(p.font().family(), 8))
        for s in self.project.subtitles:
            x0, x1 = self.t2x(s.start), self.t2x(s.end)
            if x1 < 0 or x0 > self.width():
                continue
            r = QRectF(x0, SUB_Y, max(2.0, x1 - x0 - 1), SUB_H)
            path = QPainterPath()
            path.addRoundedRect(r, 4, 4)
            p.fillPath(path, QColor("#3b3360"))
            if r.width() > 20:
                p.setPen(QColor(theme.TEXT))
                p.drawText(r.adjusted(4, 0, -2, 0), Qt.AlignVCenter | Qt.AlignLeft,
                           p.fontMetrics().elidedText(s.text, Qt.ElideRight, int(r.width() - 6)))

    # --------------------------------------------------------------- ratón
    def _hit(self, pos) -> tuple[int, str]:
        if not (VIDEO_Y <= pos.y() <= VIDEO_Y + VIDEO_H):
            return -1, ""
        for i, r in enumerate(self.clip_rects()):
            if r.left() - 2 <= pos.x() <= r.right() + 2:
                if pos.x() - r.left() <= EDGE and r.width() > 3 * EDGE:
                    return i, "left"
                if r.right() - pos.x() <= EDGE and r.width() > 3 * EDGE:
                    return i, "right"
                return i, "move"
        return -1, ""

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton or not self.project:
            return
        pos = ev.position()
        idx, mode = self._hit(pos)
        if idx >= 0:
            self.select(idx)
            c = self.project.clips[idx]
            self._drag = {"mode": mode, "idx": idx, "x0": pos.x(), "start": c.start, "end": c.end,
                          "snap": False, "drop": None}
            if mode == "move":
                self.seekRequested.emit(self.x2t(pos.x()))
        else:
            self._drag = {"mode": "seek"}
            self.seekRequested.emit(min(self.x2t(pos.x()), self.project.duration))

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if not self._drag:
            _i, mode = self._hit(pos)
            self.setCursor(Qt.SizeHorCursor if mode in ("left", "right") else
                           Qt.OpenHandCursor if mode == "move" else Qt.ArrowCursor)
            return
        d = self._drag
        if d["mode"] == "seek":
            self.seekRequested.emit(min(self.x2t(pos.x()), self.project.duration))
            return
        c = self.project.clips[d["idx"]]
        dt = (pos.x() - d["x0"]) / self.pps * c.speed
        if d["mode"] in ("left", "right"):
            if not d["snap"]:
                self.before_edit()
                d["snap"] = True
            src_dur = self.source_duration(c.source) or 1e9
            if d["mode"] == "left":
                c.start = min(max(0.0, d["start"] + dt), c.end - MIN_CLIP)
            else:
                c.end = max(min(src_dur, d["end"] + dt), c.start + MIN_CLIP)
            self.update()
        elif d["mode"] == "move" and abs(pos.x() - d["x0"]) > 6:
            self.setCursor(Qt.ClosedHandCursor)
            rects = self.clip_rects()
            drop = len(rects)
            for i, r in enumerate(rects):
                if pos.x() < r.center().x():
                    drop = i
                    break
            d["drop"] = drop
            self.update()

    def mouseReleaseEvent(self, _ev):
        d, self._drag = self._drag, None
        if not d:
            return
        if d["mode"] == "move" and d.get("drop") is not None:
            src, dst = d["idx"], d["drop"]
            if dst > src:
                dst -= 1
            if dst != src:
                self.before_edit()
                self.project.move_clip(src, dst)
                self.select(dst)
                self.edited.emit()
        elif d["mode"] in ("left", "right") and d["snap"]:
            self.edited.emit()
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def mouseDoubleClickEvent(self, ev):
        self.zoom_to_fit()

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y() or ev.angleDelta().x()
        if ev.modifiers() & Qt.ControlModifier:
            anchor = self.x2t(ev.position().x())
            self.pps = max(1.0, min(800.0, self.pps * (1.15 if delta > 0 else 1 / 1.15)))
            self.scroll = max(0.0, anchor - (ev.position().x() - LEFT_PAD) / self.pps)
        else:
            self.scroll = max(0.0, self.scroll - delta / self.pps * 0.5)
        self.update()
