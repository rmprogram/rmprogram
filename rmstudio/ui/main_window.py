"""Ventana principal del editor."""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget, QToolBar, QToolButton, QVBoxLayout,
                               QWidget, QHeaderView)

from .. import APP_NAME
from ..ai import highlights as hl
from ..ai import reframe, scenes, silence, transcribe
from ..core import exporter
from ..core.ffmpeg_utils import MediaInfo, fmt_time, make_thumbnail, probe
from ..core.project import Clip, Project, Subtitle
from . import theme
from .dialogs import ExportDialog, HighlightsDialog
from .player import PreviewPlayer
from .timeline import Timeline
from .workers import Task, start

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mts", ".mpg", ".mpeg", ".wmv", ".flv",
             ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "rmstudio")


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(12, 10, 12, 12)
    t = QLabel(title.upper())
    t.setObjectName("title")
    lay.addWidget(t)
    return f, lay


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 880)
        self.setAcceptDrops(True)
        self.project = Project()
        self.infos: dict[str, MediaInfo] = {}
        self.task: Optional[Task] = None
        self._prop_lock = False
        self._prop_snap_id = None
        os.makedirs(os.path.join(CACHE, "thumbs"), exist_ok=True)

        self._build_toolbar()
        self._build_ui()
        self._build_shortcuts()
        self._set_project(self.project)

    # ================================================================== UI
    def _build_toolbar(self):
        tb = QToolBar("Principal")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)
        logo = QLabel(f"  🎬  <b>{APP_NAME}</b>   ")
        tb.addWidget(logo)

        def act(text, tip, slot, key=None):
            a = QAction(text, self)
            a.setToolTip(f"{tip} ({key})" if key else tip)
            a.triggered.connect(slot)
            if key:
                a.setShortcut(QKeySequence(key))
            tb.addAction(a)
            return a

        act("📂 Importar", "Importar videos o audio", self.import_files, "Ctrl+I")
        act("🗂 Abrir", "Abrir proyecto", self.open_project, "Ctrl+O")
        act("💾 Guardar", "Guardar proyecto", self.save_project, "Ctrl+S")
        tb.addSeparator()
        self.undo_act = act("↶ Deshacer", "Deshacer", self.undo, "Ctrl+Z")
        self.redo_act = act("↷ Rehacer", "Rehacer", self.redo, "Ctrl+Y")
        tb.addSeparator()
        act("✂ Dividir", "Dividir en el cursor", self.split, "S")
        act("🗑 Eliminar", "Eliminar clip seleccionado", self.delete_clip, "Delete")
        act("⧉ Duplicar", "Duplicar clip", self.duplicate_clip, "Ctrl+D")
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding,
                             spacer.sizePolicy().verticalPolicy().Preferred)
        tb.addWidget(spacer)
        exp = QToolButton()
        exp.setText("⬆  Exportar")
        exp.setObjectName("exportBtn")
        exp.clicked.connect(self.export)
        tb.addWidget(exp)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        # ---- biblioteca
        lib, lib_lay = _card("Biblioteca")
        self.bin = QListWidget()
        self.bin.setViewMode(QListWidget.IconMode)
        self.bin.setIconSize(QSize(132, 74))
        self.bin.setGridSize(QSize(150, 110))
        self.bin.setResizeMode(QListWidget.Adjust)
        self.bin.setMovement(QListWidget.Static)
        self.bin.setWordWrap(True)
        self.bin.itemDoubleClicked.connect(lambda it: self.add_to_timeline(it.data(Qt.UserRole)))
        add_btn = QPushButton("＋ Añadir a la línea de tiempo")
        add_btn.clicked.connect(self._add_selected_bin)
        imp_btn = QPushButton("📂 Importar medios")
        imp_btn.setObjectName("primary")
        imp_btn.clicked.connect(self.import_files)
        lib_lay.addWidget(imp_btn)
        lib_lay.addWidget(self.bin, 1)
        lib_lay.addWidget(add_btn)

        # ---- vista previa
        prev, prev_lay = _card("Vista previa")
        self.player = PreviewPlayer()
        prev_lay.addWidget(self.player, 1)

        # ---- panel derecho
        right, right_lay = _card("Herramientas")
        tabs = QTabWidget()
        tabs.addTab(self._ai_tab(), "✨ IA")
        tabs.addTab(self._props_tab(), "🎛 Clip")
        tabs.addTab(self._subs_tab(), "💬 Subtítulos")
        right_lay.addWidget(tabs)

        top = QSplitter(Qt.Horizontal)
        top.addWidget(lib)
        top.addWidget(prev)
        top.addWidget(right)
        top.setSizes([300, 760, 360])
        top.setStretchFactor(1, 1)

        # ---- línea de tiempo
        tl, tl_lay = _card("Línea de tiempo")
        head = QHBoxLayout()
        self.tl_info = QLabel("")
        self.tl_info.setObjectName("muted")
        head.addWidget(self.tl_info)
        head.addStretch()
        hint = QLabel("Ctrl+rueda: zoom · arrastra para reordenar · bordes para recortar · doble clic: ajustar")
        hint.setObjectName("muted")
        head.addWidget(hint)
        fit_btn = QPushButton("↔ Ajustar")
        fit_btn.clicked.connect(lambda: self.timeline.zoom_to_fit())
        head.addWidget(fit_btn)
        tl_lay.addLayout(head)
        self.timeline = Timeline()
        self.timeline.before_edit = self.project_snapshot
        self.timeline.source_duration = lambda p: self.infos[p].duration if p in self.infos else 0.0
        self.timeline.seekRequested.connect(self.player.seek)
        self.timeline.selectionChanged.connect(self._on_select)
        self.timeline.edited.connect(self._after_edit)
        self.player.positionChanged.connect(self.timeline.set_playhead)
        tl_lay.addWidget(self.timeline)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(top)
        vsplit.addWidget(tl)
        vsplit.setSizes([600, 220])
        root.addWidget(vsplit)

        # ---- barra de estado
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.setRange(0, 1000)
        self.progress.hide()
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(self._cancel_task)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_btn)
        self.statusBar().showMessage("Listo · IA 100% local: sin conexión, sin tokens, sin costes")

    def _ai_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Aplicar a:"))
        self.scope = QComboBox()
        self.scope.addItems(["Toda la línea de tiempo", "Clip seleccionado"])
        row.addWidget(self.scope, 1)
        lay.addLayout(row)

        def ai_btn(text, tip, slot):
            b = QPushButton(text)
            b.setObjectName("ai")
            b.setToolTip(tip)
            b.clicked.connect(slot)
            lay.addWidget(b)
            return b

        ai_btn("🔇  Cortar silencios automáticamente",
               "Elimina pausas y silencios (ideal para vlogs, tutoriales y podcasts).", self.ai_silence)
        sens = QHBoxLayout()
        sens.addWidget(QLabel("Sensibilidad"))
        self.sil_db = QSlider(Qt.Horizontal)
        self.sil_db.setRange(-55, -20)
        self.sil_db.setValue(-35)
        self.sil_lbl = QLabel("-35 dB")
        self.sil_db.valueChanged.connect(lambda v: self.sil_lbl.setText(f"{v} dB"))
        sens.addWidget(self.sil_db, 1)
        sens.addWidget(self.sil_lbl)
        lay.addLayout(sens)
        pause = QHBoxLayout()
        pause.addWidget(QLabel("Pausa mínima (s)"))
        self.sil_min = QDoubleSpinBox()
        self.sil_min.setRange(0.2, 5.0)
        self.sil_min.setSingleStep(0.1)
        self.sil_min.setValue(0.6)
        pause.addWidget(self.sil_min)
        lay.addLayout(pause)

        ai_btn("🎞  Detectar escenas y dividir",
               "Corta el clip en cada cambio de plano.", self.ai_scenes)
        ai_btn("⭐  Encontrar mejores momentos (clips virales)",
               "Analiza el audio y las escenas para proponer clips cortos para Shorts/Reels/TikTok.",
               self.ai_highlights)
        hrow = QHBoxLayout()
        hrow.addWidget(QLabel("Duración"))
        self.hl_len = QDoubleSpinBox()
        self.hl_len.setRange(5, 180)
        self.hl_len.setValue(30)
        self.hl_len.setSuffix(" s")
        hrow.addWidget(self.hl_len)
        hrow.addWidget(QLabel("Cantidad"))
        self.hl_count = QDoubleSpinBox()
        self.hl_count.setDecimals(0)
        self.hl_count.setRange(1, 20)
        self.hl_count.setValue(3)
        hrow.addWidget(self.hl_count)
        lay.addLayout(hrow)
        ai_btn("📱  Reencuadre vertical 9:16 (sigue la cara)",
               "Convierte el proyecto a vertical y centra a la persona en cada clip.", self.ai_reframe)

        lay.addSpacing(6)
        wh = QLabel("Voz (Whisper local)")
        wh.setObjectName("title")
        lay.addWidget(wh)
        mrow = QHBoxLayout()
        self.w_model = QComboBox()
        self.w_model.addItems(transcribe.MODELS)
        self.w_model.setCurrentText("base")
        self.w_model.setToolTip("tiny = más rápido · small/medium = más preciso")
        self.w_lang = QComboBox()
        self.w_lang.addItems(["Auto", "es", "en", "pt", "fr", "it", "de"])
        self.w_lang.setCurrentText("es")
        mrow.addWidget(QLabel("Modelo"))
        mrow.addWidget(self.w_model)
        mrow.addWidget(QLabel("Idioma"))
        mrow.addWidget(self.w_lang)
        lay.addLayout(mrow)
        ai_btn("💬  Subtítulos automáticos", "Transcribe la voz y genera subtítulos dinámicos.", self.ai_subtitles)
        ai_btn("🧹  Quitar muletillas (eh, este, um…)", "Corta las muletillas detectadas en la voz.",
               self.ai_fillers)
        if not transcribe.is_available():
            note = QLabel("ℹ Para subtítulos y muletillas instala:\n   pip install faster-whisper")
            note.setObjectName("muted")
            lay.addWidget(note)
        lay.addStretch()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setWidget(w)
        return sc

    def _props_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.p_label = QLineEdit()
        self.p_start = QDoubleSpinBox()
        self.p_end = QDoubleSpinBox()
        for sb in (self.p_start, self.p_end):
            sb.setDecimals(3)
            sb.setRange(0, 1e6)
            sb.setSingleStep(0.1)
            sb.setSuffix(" s")
        self.p_speed = QDoubleSpinBox()
        self.p_speed.setRange(0.25, 4.0)
        self.p_speed.setSingleStep(0.25)
        self.p_speed.setSuffix(" ×")
        self.p_vol = QSlider(Qt.Horizontal)
        self.p_vol.setRange(0, 200)
        self.p_vol_lbl = QLabel("100%")
        vrow = QHBoxLayout()
        vrow.addWidget(self.p_vol, 1)
        vrow.addWidget(self.p_vol_lbl)
        self.p_info = QLabel("Selecciona un clip en la línea de tiempo")
        self.p_info.setObjectName("muted")
        self.p_info.setWordWrap(True)
        form.addRow(self.p_info)
        form.addRow("Nombre", self.p_label)
        form.addRow("Entrada", self.p_start)
        form.addRow("Salida", self.p_end)
        form.addRow("Velocidad", self.p_speed)
        form.addRow("Volumen", vrow)
        speeds = QHBoxLayout()
        for s in (0.5, 1.0, 1.5, 2.0):
            b = QPushButton(f"{s:g}×")
            b.clicked.connect(lambda _=False, v=s: self.p_speed.setValue(v))
            speeds.addWidget(b)
        form.addRow("", speeds)
        self.p_label.editingFinished.connect(self._props_changed)
        for sb in (self.p_start, self.p_end, self.p_speed):
            sb.valueChanged.connect(self._props_changed)
        self.p_vol.valueChanged.connect(self._props_changed)
        self._set_props_enabled(False)
        return w

    def _subs_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        self.subs_table = QTableWidget(0, 3)
        self.subs_table.setHorizontalHeaderLabels(["Inicio", "Fin", "Texto"])
        self.subs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.subs_table.verticalHeader().hide()
        self.subs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.subs_table.setStyleSheet(f"QTableWidget {{ background: {theme.PANEL_2}; border: none; }}")
        self.subs_table.itemChanged.connect(self._sub_edited)
        self.subs_table.cellDoubleClicked.connect(
            lambda r, _c: self.player.seek(self.project.subtitles[r].start) if r < len(self.project.subtitles) else None)
        lay.addWidget(self.subs_table, 1)
        row = QHBoxLayout()
        add = QPushButton("＋ Añadir en el cursor")
        add.clicked.connect(self._add_sub)
        rm = QPushButton("🗑 Quitar")
        rm.clicked.connect(self._remove_sub)
        clear = QPushButton("Borrar todos")
        clear.clicked.connect(self._clear_subs)
        row.addWidget(add)
        row.addWidget(rm)
        row.addWidget(clear)
        lay.addLayout(row)
        return w

    def _build_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Space), self, self.player.toggle)
        QShortcut(QKeySequence(Qt.Key_Home), self, lambda: self.player.seek(0))
        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self.player.seek(self.player.current_time - 1 / 30))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self.player.seek(self.player.current_time + 1 / 30))
        QShortcut(QKeySequence("J"), self, lambda: self.player.seek(self.player.current_time - 5))
        QShortcut(QKeySequence("L"), self, lambda: self.player.seek(self.player.current_time + 5))
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.redo)

    # ================================================================== proyecto
    def _set_project(self, p: Project):
        self.project = p
        self.timeline.set_project(p)
        self.player.set_project(p)
        self._refresh_all()

    def project_snapshot(self):
        self.project.snapshot()

    def _after_edit(self):
        self.player.refresh()
        self._refresh_all()

    def _refresh_all(self):
        p = self.project
        self.tl_info.setText(f"{len(p.clips)} clips · {fmt_time(p.duration)} · {p.width}×{p.height}"
                             + (f" · {len(p.subtitles)} subtítulos" if p.subtitles else ""))
        self.undo_act.setEnabled(p.can_undo())
        self.redo_act.setEnabled(p.can_redo())
        if self.timeline.selected >= len(p.clips):
            self.timeline.selected = len(p.clips) - 1
        self._on_select(self.timeline.selected)
        self._fill_subs_table()
        self.timeline.update()
        name = os.path.basename(p.path) if p.path else "Sin título"
        self.setWindowTitle(f"{name} — {APP_NAME}")

    def undo(self):
        if self.project.undo():
            self._after_edit()

    def redo(self):
        if self.project.redo():
            self._after_edit()

    def split(self):
        self.project_snapshot()
        if self.project.split_at(self.player.current_time):
            self._after_edit()
        else:
            self.project.undo()

    def delete_clip(self):
        i = self.timeline.selected
        if 0 <= i < len(self.project.clips):
            self.project_snapshot()
            self.project.remove_clip(i)
            self._after_edit()

    def duplicate_clip(self):
        i = self.timeline.selected
        if 0 <= i < len(self.project.clips):
            self.project_snapshot()
            c = self.project.clips[i]
            self.project.add_clip(c.source, c.start, c.end, index=i + 1, label=c.label)
            nc = self.project.clips[i + 1]
            nc.speed, nc.volume, nc.crop_x = c.speed, c.volume, c.crop_x
            self._after_edit()

    # ================================================================== medios
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        projs = [p for p in paths if p.endswith(".rmproj")]
        if projs:
            self._load_project(projs[0])
            return
        added = self._import_paths(paths)
        for p in added:  # al soltar, también se añaden a la línea de tiempo
            self.add_to_timeline(p)

    def import_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Importar medios", "", "Medios (" + " ".join("*" + e for e in VIDEO_EXT) + ");;Todos (*)")
        self._import_paths(paths)

    def _import_paths(self, paths) -> list[str]:
        added = []
        for path in paths:
            if not path.lower().endswith(VIDEO_EXT) or not os.path.exists(path):
                continue
            path = os.path.abspath(path)
            if path in self.infos:
                added.append(path)
                continue
            try:
                info = probe(path)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "No se pudo importar", str(exc))
                continue
            self.infos[path] = info
            it = QListWidgetItem(f"{os.path.basename(path)}\n{fmt_time(info.duration, False)}")
            it.setData(Qt.UserRole, path)
            it.setToolTip(f"{path}\n{info.width}×{info.height} · {info.fps:.2f} fps")
            self.bin.addItem(it)
            self._make_thumb(path, it)
            added.append(path)
        if added and not self.project.clips:
            first = self.infos[added[0]]
            if first.has_video and first.width and first.height:
                self.project.width, self.project.height = first.width, first.height
                self.project.fps = round(first.fps, 3) or 30.0
        return added

    def _make_thumb(self, path: str, item: Optional[QListWidgetItem] = None):
        key = hashlib.md5(path.encode()).hexdigest()
        out = os.path.join(CACHE, "thumbs", key + ".png")
        info = self.infos[path]

        def job(progress=None, cancel=None):
            if not os.path.exists(out) and info.has_video:
                make_thumbnail(path, out, at=min(1.0, info.duration / 3))
            return out

        def done(png):
            if os.path.exists(png):
                pix = QPixmap(png)
                self.timeline.thumbs[path] = pix
                if item is not None:
                    item.setIcon(QIcon(pix))
                self.timeline.update()

        t = Task(job)
        t.signals.done.connect(done)
        start(t)

    def _add_selected_bin(self):
        for it in self.bin.selectedItems():
            self.add_to_timeline(it.data(Qt.UserRole))

    def add_to_timeline(self, path: str):
        info = self.infos.get(path)
        if not info:
            return
        self.project_snapshot()
        self.project.add_clip(path, 0.0, info.duration)
        self._after_edit()
        if len(self.project.clips) == 1:
            self.timeline.zoom_to_fit()
            self.player.seek(0)

    # ================================================================== archivo
    def save_project(self):
        path = self.project.path
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Guardar proyecto", "proyecto.rmproj",
                                                  "Proyecto RM Studio (*.rmproj)")
            if not path:
                return
            if not path.endswith(".rmproj"):
                path += ".rmproj"
        self.project.save(path)
        self.statusBar().showMessage(f"Proyecto guardado: {path}", 4000)
        self._refresh_all()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", "", "Proyecto RM Studio (*.rmproj)")
        if path:
            self._load_project(path)

    def _load_project(self, path: str):
        try:
            p = Project.load(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo abrir el proyecto:\n{exc}")
            return
        missing = sorted({c.source for c in p.clips if not os.path.exists(c.source)})
        if missing:
            QMessageBox.warning(self, "Archivos no encontrados", "Faltan:\n" + "\n".join(missing))
            p.clips = [c for c in p.clips if os.path.exists(c.source)]
        self._import_paths(sorted({c.source for c in p.clips}))
        self._set_project(p)
        self.timeline.zoom_to_fit()

    # ================================================================== propiedades
    def _set_props_enabled(self, on: bool):
        for wdg in (self.p_label, self.p_start, self.p_end, self.p_speed, self.p_vol):
            wdg.setEnabled(on)

    def _on_select(self, idx: int):
        self._prop_snap_id = None
        self._prop_lock = True
        try:
            if 0 <= idx < len(self.project.clips):
                c = self.project.clips[idx]
                info = self.infos.get(c.source)
                self._set_props_enabled(True)
                self.p_label.setText(c.label)
                self.p_start.setValue(c.start)
                self.p_end.setMaximum(info.duration if info else 1e6)
                self.p_end.setValue(c.end)
                self.p_speed.setValue(c.speed)
                self.p_vol.setValue(int(round(c.volume * 100)))
                self.p_vol_lbl.setText(f"{int(round(c.volume * 100))}%")
                self.p_info.setText(f"Clip {idx + 1}: {os.path.basename(c.source)}\n"
                                    f"Duración en la línea de tiempo: {fmt_time(c.duration)}")
            else:
                self._set_props_enabled(False)
                self.p_info.setText("Selecciona un clip en la línea de tiempo")
        finally:
            self._prop_lock = False

    def _props_changed(self, *_):
        if self._prop_lock:
            return
        idx = self.timeline.selected
        if not (0 <= idx < len(self.project.clips)):
            return
        c = self.project.clips[idx]
        if self._prop_snap_id != c.id:  # un paso de deshacer por sesión de edición del clip
            self.project_snapshot()
            self._prop_snap_id = c.id
        c.label = self.p_label.text()
        if self.p_end.value() - self.p_start.value() >= 0.05:
            c.start, c.end = self.p_start.value(), self.p_end.value()
        c.speed = self.p_speed.value()
        c.volume = self.p_vol.value() / 100
        self.p_vol_lbl.setText(f"{self.p_vol.value()}%")
        self.player.refresh()
        self.timeline.update()
        self.tl_info.setText(f"{len(self.project.clips)} clips · {fmt_time(self.project.duration)}")

    # ================================================================== subtítulos
    def _fill_subs_table(self):
        t = self.subs_table
        t.blockSignals(True)
        t.setRowCount(len(self.project.subtitles))
        for r, s in enumerate(self.project.subtitles):
            for col, val in enumerate((fmt_time(s.start), fmt_time(s.end), s.text)):
                it = QTableWidgetItem(val)
                if col < 2:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(r, col, it)
        t.blockSignals(False)

    def _sub_edited(self, item: QTableWidgetItem):
        if item.column() == 2 and item.row() < len(self.project.subtitles):
            self.project_snapshot()
            self.project.subtitles[item.row()].text = item.text()
            self.timeline.update()

    def _add_sub(self):
        t = self.player.current_time
        self.project_snapshot()
        self.project.subtitles.append(Subtitle(t, t + 2.0, "Nuevo subtítulo"))
        self.project.subtitles.sort(key=lambda s: s.start)
        self._refresh_all()

    def _remove_sub(self):
        rows = sorted({i.row() for i in self.subs_table.selectedIndexes()}, reverse=True)
        if rows:
            self.project_snapshot()
            for r in rows:
                del self.project.subtitles[r]
            self._refresh_all()

    def _clear_subs(self):
        if self.project.subtitles:
            self.project_snapshot()
            self.project.subtitles.clear()
            self._refresh_all()

    # ================================================================== tareas
    def _run(self, label: str, fn, on_done, *args, **kwargs):
        if self.task is not None:
            QMessageBox.information(self, "Ocupado", "Espera a que termine la tarea actual.")
            return
        self.player.pause()
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_btn.show()
        self.statusBar().showMessage(label + "…")
        task = Task(fn, *args, **kwargs)
        task.signals.progress.connect(lambda v: self.progress.setValue(int(v * 1000)))

        def finish():
            self.task = None
            self.progress.hide()
            self.cancel_btn.hide()

        def ok(res):
            finish()
            on_done(res)

        def fail(msg):
            finish()
            self.statusBar().showMessage("Tarea cancelada" if "cancel" in msg.lower() else "Error", 5000)
            if "cancel" not in msg.lower():
                QMessageBox.critical(self, "Error", msg)

        task.signals.done.connect(ok)
        task.signals.failed.connect(fail)
        self.task = start(task)

    def _cancel_task(self):
        if self.task:
            self.task.cancel()

    def _target_indices(self) -> list[int]:
        if not self.project.clips:
            QMessageBox.information(self, APP_NAME, "Primero añade algún video a la línea de tiempo.")
            return []
        if self.scope.currentIndex() == 1:
            if 0 <= self.timeline.selected < len(self.project.clips):
                return [self.timeline.selected]
            QMessageBox.information(self, APP_NAME, "Selecciona un clip en la línea de tiempo.")
            return []
        return list(range(len(self.project.clips)))

    def _per_clip(self, indices, fn):
        """Ejecuta fn(clip, progress, cancel) por cada clip y combina el progreso."""
        clips = [Clip(**self.project.clips[i].__dict__) for i in indices]
        ids = [c.id for c in clips]

        def job(progress=None, cancel=None):
            results = []
            for k, c in enumerate(clips):
                sub = (lambda v, k=k: progress((k + v) / len(clips))) if progress else None
                results.append(fn(c, sub, cancel))
            return list(zip(ids, results))

        return job

    def _apply_ranges(self, results, what: str):
        self.project_snapshot()
        before = len(self.project.clips)
        before_dur = self.project.duration
        for cid, ranges in results:
            idx = self.project.index_of(cid)
            if idx >= 0 and ranges:
                self.project.split_clip_into_ranges(idx, ranges)
        self._after_edit()
        saved = before_dur - self.project.duration
        msg = f"{what}: {before} → {len(self.project.clips)} clips"
        if saved > 0.05:
            msg += f" · {fmt_time(saved)} eliminados"
        self.statusBar().showMessage(msg, 8000)
        self.timeline.zoom_to_fit()

    # ---------------------------------------------------------------- IA
    def ai_silence(self):
        idx = self._target_indices()
        if not idx:
            return
        db, mn = self.sil_db.value(), self.sil_min.value()

        def per(c, progress, cancel):
            sil = silence.detect_silences(c.source, c.start, c.end, noise_db=db, min_silence=mn,
                                          progress=progress, cancel=cancel)
            return silence.keep_ranges(c.start, c.end, sil)

        self._run("Cortando silencios", self._per_clip(idx, per),
                  lambda r: self._apply_ranges(r, "Silencios eliminados"))

    def ai_scenes(self):
        idx = self._target_indices()
        if not idx:
            return

        def per(c, progress, cancel):
            cuts = scenes.detect_scenes(c.source, c.start, c.end, progress=progress, cancel=cancel)
            return scenes.ranges_from_cuts(c.start, c.end, cuts)

        self._run("Detectando escenas", self._per_clip(idx, per),
                  lambda r: self._apply_ranges(r, "Escenas detectadas"))

    def _whisper_args(self):
        lang = self.w_lang.currentText()
        return self.w_model.currentText(), (None if lang == "Auto" else lang)

    def _check_whisper(self) -> bool:
        if transcribe.is_available():
            return True
        QMessageBox.information(
            self, "Módulo opcional",
            "Esta función usa Whisper en tu propio equipo (gratis, sin tokens).\n\n"
            "Instálalo con:\n    pip install faster-whisper\n\n"
            "La primera vez se descarga el modelo (~145 MB para 'base').")
        return False

    def ai_subtitles(self):
        idx = self._target_indices()
        if not idx or not self._check_whisper():
            return
        model, lang = self._whisper_args()

        def per(c, progress, cancel):
            segs = transcribe.transcribe(c.source, c.start, c.end, model=model, language=lang,
                                         progress=progress, cancel=cancel)
            return transcribe.to_caption_chunks(segs)

        def done(results):
            self.project_snapshot()
            new = []
            for cid, chunks in results:
                i = self.project.index_of(cid)
                if i < 0:
                    continue
                c, t0 = self.project.clips[i], self.project.clip_start(i)
                for s, e, text in chunks:
                    s, e = max(s, c.start), min(e, c.end)
                    if e > s:
                        new.append(Subtitle(t0 + (s - c.start) / c.speed, t0 + (e - c.start) / c.speed, text))
            spans = []
            for cid, _ in results:
                i = self.project.index_of(cid)
                if i >= 0:
                    t0 = self.project.clip_start(i)
                    spans.append((t0, t0 + self.project.clips[i].duration))
            keep = [s for s in self.project.subtitles
                    if not any(s.start < b and s.end > a for a, b in spans)]
            self.project.subtitles = sorted(keep + new, key=lambda s: s.start)
            self._refresh_all()
            self.statusBar().showMessage(f"{len(new)} subtítulos generados localmente", 8000)

        self._run("Transcribiendo con Whisper local", self._per_clip(idx, per), done)

    def ai_fillers(self):
        idx = self._target_indices()
        if not idx or not self._check_whisper():
            return
        model, lang = self._whisper_args()

        def per(c, progress, cancel):
            segs = transcribe.transcribe(c.source, c.start, c.end, model=model, language=lang,
                                         progress=progress, cancel=cancel)
            fill = transcribe.filler_ranges(segs)
            return silence.keep_ranges(c.start, c.end, fill, padding=0.0, min_keep=0.1) if fill else []

        self._run("Buscando muletillas", self._per_clip(idx, per),
                  lambda r: self._apply_ranges(r, "Muletillas eliminadas"))

    def ai_highlights(self):
        if not self.project.clips and self.bin.count() == 0:
            QMessageBox.information(self, APP_NAME, "Importa un video primero.")
            return
        if 0 <= self.timeline.selected < len(self.project.clips):
            c = self.project.clips[self.timeline.selected]
            src, s0, s1 = c.source, c.start, c.end
        elif self.project.clips:
            c = self.project.clips[0]
            src, s0, s1 = c.source, c.start, c.end
        else:
            src = self.bin.currentItem().data(Qt.UserRole) if self.bin.currentItem() else self.bin.item(0).data(Qt.UserRole)
            src, s0, s1 = src, 0.0, self.infos[src].duration
        clip_len, count = self.hl_len.value(), int(self.hl_count.value())
        info = self.infos[src]

        def job(progress=None, cancel=None):
            cuts = []
            if info.has_video:
                cuts = scenes.detect_scenes(src, s0, s1, progress=lambda v: progress(v * 0.7), cancel=cancel)
            res = hl.find_highlights(src, info.duration, clip_len=clip_len, count=count,
                                     start=s0, end=s1, scene_cuts=cuts)
            progress(1.0)
            return res

        self._run("Buscando los mejores momentos", job, lambda res: self._show_highlights(src, res))

    def _show_highlights(self, src: str, res):
        dlg = HighlightsDialog(self, src, res)
        if not dlg.exec():
            return
        chosen = dlg.chosen()
        if not chosen:
            return
        if dlg.action == "timeline":
            p = Project(width=1080 if dlg.vertical.isChecked() else self.project.width,
                        height=1920 if dlg.vertical.isChecked() else self.project.height, fps=self.project.fps)
            for k, h in enumerate(chosen, 1):
                p.add_clip(src, h.start, h.end, label=f"Momento {k}")
            self._set_project(p)
            self.timeline.zoom_to_fit()
            if dlg.vertical.isChecked():
                self.ai_reframe(ask=False)
            return
        if dlg.subs.isChecked() and not self._check_whisper():
            return
        folder = dlg.folder.text()
        vertical, subs = dlg.vertical.isChecked(), dlg.subs.isChecked()
        model, lang = self._whisper_args()
        info = self.infos[src]
        base = os.path.splitext(os.path.basename(src))[0]

        def job(progress=None, cancel=None):
            os.makedirs(folder, exist_ok=True)
            outs = []
            n = len(chosen)
            for k, h in enumerate(chosen):
                sub = lambda v, k=k: progress((k + v) / n)  # noqa: E731
                w, hh = (1080, 1920) if vertical else (self.project.width, self.project.height)
                s = exporter.ExportSettings(output=os.path.join(folder, f"{base}_momento_{k + 1}.mp4"),
                                            width=w, height=hh, fps=self.project.fps,
                                            fit="fill" if vertical else "fit", burn_subtitles=subs)
                crop = None
                if vertical and info.has_video:
                    cx = reframe.face_center_x(src, h.start, h.end)
                    if cx is not None:
                        crop = reframe.crop_offset_for(cx, info.width, info.height, w, hh)
                subtitles = None
                if subs:
                    segs = transcribe.transcribe(src, h.start, h.end, model=model, language=lang, cancel=cancel)
                    subtitles = [Subtitle(a, b, t) for a, b, t in transcribe.to_caption_chunks(segs, max_words=4)]
                exporter.export_segment(src, h.start, h.end, s, crop_x=crop, subtitles=subtitles,
                                        progress=sub, cancel=cancel)
                outs.append(s.output)
            return outs

        self._run("Exportando clips", job,
                  lambda outs: QMessageBox.information(self, "Clips listos",
                                                       f"Se exportaron {len(outs)} clips en:\n{folder}"))

    def ai_reframe(self, ask: bool = True):
        if not self.project.clips:
            QMessageBox.information(self, APP_NAME, "Primero añade algún video a la línea de tiempo.")
            return
        idx = list(range(len(self.project.clips)))
        W, H = 1080, 1920

        def per(c, progress, cancel):
            info = self.infos.get(c.source)
            if not info or not info.has_video:
                return None
            cx = reframe.face_center_x(c.source, c.start, c.end)
            if progress:
                progress(1.0)
            return reframe.crop_offset_for(cx if cx is not None else 0.5, info.width, info.height, W, H)

        def done(results):
            self.project_snapshot()
            self.project.width, self.project.height = W, H
            for cid, crop in results:
                i = self.project.index_of(cid)
                if i >= 0:
                    self.project.clips[i].crop_x = crop
            self._refresh_all()
            self.statusBar().showMessage("Proyecto en formato vertical 9:16 con reencuadre automático", 8000)

        self._run("Reencuadrando a 9:16 (detectando caras)", self._per_clip(idx, per), done)

    # ================================================================== exportar
    def export(self):
        if not self.project.clips:
            QMessageBox.information(self, APP_NAME, "La línea de tiempo está vacía.")
            return
        first = self.project.clips[0].source
        default = os.path.join(os.path.dirname(first), os.path.splitext(os.path.basename(first))[0] + "_editado.mp4")
        dlg = ExportDialog(self, default, self.project.width, self.project.height, bool(self.project.subtitles),
                           fps=self.project.fps)
        if not dlg.exec():
            return
        s = dlg.settings()
        proj = Project(clips=[Clip(**c.__dict__) for c in self.project.clips],
                       subtitles=list(self.project.subtitles))
        infos = dict(self.infos)

        def job(progress=None, cancel=None):
            return exporter.export_project(proj, s, progress=progress, cancel=cancel, infos=infos)

        self._run("Exportando video", job,
                  lambda out: QMessageBox.information(self, "Exportación completa", f"Video guardado en:\n{out}"))

    def closeEvent(self, ev):
        if self.task:
            self.task.cancel()
        self.player.stop()
        super().closeEvent(ev)
