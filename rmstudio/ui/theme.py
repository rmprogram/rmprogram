"""Tema oscuro moderno para la interfaz."""

ACCENT = "#7c5cff"
ACCENT_2 = "#22d3ee"
BG = "#121218"
PANEL = "#1b1b24"
PANEL_2 = "#23232f"
BORDER = "#2e2e3d"
TEXT = "#e8e8f0"
MUTED = "#9a9ab0"

CLIP_COLORS = ["#6d5dfc", "#2fb5d2", "#e0619b", "#f59e0b", "#22c55e", "#ef4444", "#a855f7", "#14b8a6"]

QSS = f"""
* {{ font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif; font-size: 13px; color: {TEXT}; }}
QMainWindow, QWidget#central {{ background: {BG}; }}
QToolBar {{ background: {PANEL}; border: none; border-bottom: 1px solid {BORDER}; padding: 4px; spacing: 4px; }}
QToolBar QToolButton {{ background: transparent; border-radius: 6px; padding: 6px 10px; }}
QToolBar QToolButton:hover {{ background: {PANEL_2}; }}
QToolBar QToolButton:pressed {{ background: {BORDER}; }}
QToolButton#exportBtn {{ background: {ACCENT}; color: white; font-weight: 600; padding: 6px 16px; }}
QToolButton#exportBtn:hover {{ background: #8f74ff; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QSplitter::handle {{ background: {BG}; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#title {{ font-size: 12px; font-weight: 700; color: {MUTED}; letter-spacing: 1px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#time {{ font-family: "JetBrains Mono", "Consolas", monospace; font-size: 14px; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: #5a5a6e; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: #8f74ff; }}
QPushButton#ai {{ text-align: left; padding: 10px 12px; }}
QPushButton#play {{ border-radius: 18px; min-width: 36px; min-height: 36px; font-size: 15px; background: {ACCENT}; border: none; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border-radius: 8px; padding: 4px; margin: 2px; }}
QListWidget::item:selected {{ background: {PANEL_2}; border: 1px solid {ACCENT}; }}
QListWidget::item:hover {{ background: {PANEL_2}; }}
QTabWidget::pane {{ border: none; background: transparent; }}
QScrollArea, QScrollArea > QWidget > QWidget, QTabWidget > QStackedWidget > QWidget {{ background: transparent; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; color: {MUTED}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; selection-background-color: {ACCENT}; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }}
QProgressBar {{ background: {PANEL_2}; border: none; border-radius: 4px; height: 8px; text-align: center; font-size: 10px; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2}); border-radius: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {BORDER}; background: {PANEL_2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {MUTED}; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {ACCENT}; }}
QDialog {{ background: {PANEL}; }}
"""
