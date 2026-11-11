"""Punto de entrada de la aplicación gráfica."""
from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import APP_NAME
from ..core.ffmpeg_utils import FFmpegError, ffmpeg_bin, ffprobe_bin
from . import theme
from .main_window import MainWindow


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.QSS)
    app.setFont(QFont(app.font().family(), 10))
    try:
        ffmpeg_bin()
        ffprobe_bin()
    except FFmpegError as exc:
        QMessageBox.critical(None, APP_NAME, str(exc) + "\n\nDescarga: https://ffmpeg.org/download.html")
        return 1
    win = MainWindow()
    win.show()
    files = [a for a in argv[1:] if not a.startswith("-")]
    if files:
        if files[0].endswith(".rmproj"):
            win._load_project(files[0])
        else:
            for p in win._import_paths(files):
                win.add_to_timeline(p)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
