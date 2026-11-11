"""Diálogos: exportación y resultados de "mejores momentos"."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from ..core.exporter import PRESETS, QUALITY, SPEED, ExportSettings
from ..core.ffmpeg_utils import fmt_time

FITS = {
    "Ajustar (barras negras)": "fit",
    "Rellenar (recortar)": "fill",
    "Fondo desenfocado (ideal 9:16)": "blur",
}


class ExportDialog(QDialog):
    def __init__(self, parent, default_path: str, width: int, height: int, has_subs: bool, fps: float = 30.0):
        super().__init__(parent)
        self.setWindowTitle("Exportar video")
        self.setMinimumWidth(460)
        self.fps = fps
        form = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItems(PRESETS.keys())
        for i, (w, h) in enumerate(PRESETS.values()):
            if (w, h) == (width, height):
                self.preset.setCurrentIndex(i)
        self.fit = QComboBox()
        self.fit.addItems(FITS.keys())
        self.quality = QComboBox()
        self.quality.addItems(QUALITY.keys())
        self.quality.setCurrentText("Normal")
        self.speed = QComboBox()
        self.speed.addItems(SPEED.keys())
        self.burn = QCheckBox("Incrustar subtítulos en el video")
        self.burn.setChecked(has_subs)
        self.burn.setEnabled(has_subs)
        self.srt = QCheckBox("Guardar también archivo .srt")
        self.srt.setEnabled(has_subs)
        self.path = QLineEdit(default_path)
        browse = QPushButton("…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        form.addRow("Formato", self.preset)
        form.addRow("Encuadre", self.fit)
        form.addRow("Calidad", self.quality)
        form.addRow("Velocidad", self.speed)
        form.addRow("", self.burn)
        form.addRow("", self.srt)
        form.addRow("Archivo", row)
        self.preset.currentTextChanged.connect(self._auto_fit)
        self._auto_fit(self.preset.currentText())

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Exportar")
        btns.button(QDialogButtonBox.Ok).setObjectName("primary")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        hint = QLabel("La exportación usa FFmpeg en tu equipo: sin nube, sin costes.")
        hint.setObjectName("muted")
        lay.addWidget(hint)
        lay.addWidget(btns)

    def _auto_fit(self, name: str):
        w, h = PRESETS[name]
        self.fit.setCurrentText("Fondo desenfocado (ideal 9:16)" if h > w else "Ajustar (barras negras)")

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Guardar como", self.path.text(), "Video MP4 (*.mp4)")
        if path:
            self.path.setText(path if path.lower().endswith(".mp4") else path + ".mp4")

    def settings(self) -> ExportSettings:
        w, h = PRESETS[self.preset.currentText()]
        return ExportSettings(
            output=self.path.text(), width=w, height=h, fps=self.fps, fit=FITS[self.fit.currentText()],
            crf=QUALITY[self.quality.currentText()], preset=SPEED[self.speed.currentText()],
            burn_subtitles=self.burn.isChecked(), write_srt=self.srt.isChecked(),
        )


class HighlightsDialog(QDialog):
    """Muestra los momentos encontrados y permite usarlos."""

    def __init__(self, parent, source: str, highlights):
        super().__init__(parent)
        self.setWindowTitle("Mejores momentos detectados")
        self.setMinimumWidth(480)
        self.action = None
        self.list = QListWidget()
        for k, h in enumerate(highlights, 1):
            it = QListWidgetItem(f"⭐ Momento {k}   {fmt_time(h.start, False)} → {fmt_time(h.end, False)}"
                                 f"   ({h.end - h.start:.0f} s · puntuación {h.score:.0f})")
            it.setCheckState(Qt.Checked)
            self.list.addItem(it)
        self.highlights = highlights
        self.vertical = QCheckBox("Formato vertical 9:16 con reencuadre automático a la cara")
        self.vertical.setChecked(True)
        self.subs = QCheckBox("Subtítulos automáticos (requiere faster-whisper)")
        self.folder = QLineEdit(os.path.join(os.path.dirname(source), "clips"))

        to_tl = QPushButton("Abrir en la línea de tiempo")
        to_tl.clicked.connect(lambda: self._done("timeline"))
        exp = QPushButton("Exportar clips")
        exp.setObjectName("primary")
        exp.clicked.connect(lambda: self._done("export"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Fuente: {os.path.basename(source)}"))
        lay.addWidget(self.list)
        lay.addWidget(self.vertical)
        lay.addWidget(self.subs)
        row = QHBoxLayout()
        row.addWidget(QLabel("Carpeta:"))
        row.addWidget(self.folder, 1)
        lay.addLayout(row)
        b = QHBoxLayout()
        b.addStretch()
        b.addWidget(to_tl)
        b.addWidget(exp)
        lay.addLayout(b)

    def _done(self, action: str):
        self.action = action
        self.accept()

    def chosen(self):
        return [h for i, h in enumerate(self.highlights) if self.list.item(i).checkState() == Qt.Checked]
