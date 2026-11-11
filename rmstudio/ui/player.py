"""Vista previa en tiempo real que reproduce la línea de tiempo sin renderizar."""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.ffmpeg_utils import fmt_time
from ..core.project import Project


class PreviewPlayer(QWidget):
    positionChanged = Signal(float)  # tiempo en la línea de tiempo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Optional[Project] = None
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget(self)
        self.video.setStyleSheet("background: black; border-radius: 10px;")
        self.player.setVideoOutput(self.video)

        self._idx = -1
        self._source = ""
        self._pending_ms: Optional[int] = None
        self._playing = False
        self._t = 0.0

        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("play")
        self.play_btn.setToolTip("Reproducir / pausar (Espacio)")
        self.play_btn.clicked.connect(self.toggle)
        back = QPushButton("⏮")
        back.setToolTip("Ir al inicio (Inicio)")
        back.clicked.connect(lambda: self.seek(0))
        self.time = QLabel("00:00.000 / 00:00.000")
        self.time.setObjectName("time")

        ctr = QHBoxLayout()
        ctr.addWidget(back)
        ctr.addStretch()
        ctr.addWidget(self.play_btn)
        ctr.addStretch()
        ctr.addWidget(self.time)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.video, 1)
        lay.addLayout(ctr)

        self.player.positionChanged.connect(self._on_pos)
        self.player.mediaStatusChanged.connect(self._on_status)
        self._tick = QTimer(self, interval=40, timeout=self._update_label)

    # ---------------------------------------------------------------- API
    def set_project(self, p: Project):
        self.project = p
        self.stop()
        self._idx, self._source = -1, ""
        self.player.setSource(QUrl())
        self.seek(0)

    @property
    def current_time(self) -> float:
        return self._t

    def toggle(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if not self.project or not self.project.clips:
            return
        if self._t >= self.project.duration - 0.05:
            self.seek(0)
        self._playing = True
        self.play_btn.setText("⏸")
        self._apply_clip_settings()
        self.player.play()
        self._tick.start()

    def pause(self):
        self._playing = False
        self.play_btn.setText("▶")
        self.player.pause()
        self._tick.stop()

    def stop(self):
        self.pause()

    def seek(self, t: float):
        if not self.project or not self.project.clips:
            self._t = 0.0
            self._update_label()
            self.positionChanged.emit(0.0)
            return
        t = max(0.0, min(t, self.project.duration))
        idx, src_t = self.project.source_time(t)
        self._t = t
        self._load(idx, src_t)
        self.positionChanged.emit(t)
        self._update_label()

    def refresh(self):
        """Recalcular después de editar la línea de tiempo."""
        self._idx = -1
        self.seek(min(self._t, self.project.duration if self.project else 0))

    # ---------------------------------------------------------------- interno
    def _load(self, idx: int, src_t: float):
        clip = self.project.clips[idx]
        self._idx = idx
        ms = int(src_t * 1000)
        if os.path.abspath(clip.source) != self._source:
            self._source = os.path.abspath(clip.source)
            self._pending_ms = ms
            self.player.setSource(QUrl.fromLocalFile(self._source))
            if self._playing:
                self.player.play()
        else:
            self.player.setPosition(ms)
        self._apply_clip_settings()

    def _apply_clip_settings(self):
        if 0 <= self._idx < len(self.project.clips):
            c = self.project.clips[self._idx]
            self.player.setPlaybackRate(c.speed)
            self.audio.setVolume(min(1.0, c.volume))

    def _on_status(self, status):
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and self._pending_ms is not None:
            self.player.setPosition(self._pending_ms)
            self._pending_ms = None
            if self._playing:
                self.player.play()
            else:  # mostrar el fotograma sin reproducir
                self.player.pause()

    def _on_pos(self, ms: int):
        if not self.project or not (0 <= self._idx < len(self.project.clips)) or self._pending_ms is not None:
            return
        c = self.project.clips[self._idx]
        src_t = ms / 1000
        if not self._playing:
            return
        if src_t >= c.end - 0.02:
            nxt = self._idx + 1
            if nxt < len(self.project.clips):
                start = self.project.clip_start(nxt)
                self._t = start
                self._load(nxt, self.project.clips[nxt].start)
            else:
                self._t = self.project.duration
                self.pause()
            self.positionChanged.emit(self._t)
            return
        self._t = self.project.clip_start(self._idx) + max(0.0, src_t - c.start) / c.speed
        self.positionChanged.emit(self._t)

    def _update_label(self):
        dur = self.project.duration if self.project else 0
        self.time.setText(f"{fmt_time(self._t)} / {fmt_time(dur)}")
