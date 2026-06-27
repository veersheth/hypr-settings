import fcntl
import os
import sys
import tempfile
from PySide6.QtCore import QSize
from PySide6.QtGui import QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from wifi_tab import WifiTab
from bluetooth_tab import BluetoothTab
from displays_tab import DisplaysTab
from sound_tab import SoundTab
from apps_tab import AppsTab
from appearance_tab import AppearanceTab
from system_tab import SystemTab

_LOCK_FILE = os.path.join(tempfile.gettempdir(), f"hypr-settings-{os.getenv('USER', 'user')}.lock")
_lock_fh = None


def _acquire_lock():
    global _lock_fh
    _lock_fh = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


BG           = "#0d0d0d"
BG_SIDEBAR   = "#080808"
BG_RAISED    = "#111111"
BG_HOVER     = "#1a1a1a"
BG_PRESS     = "#080808"

TEXT         = "#d8d8d8"
TEXT_BRIGHT  = "#f0f0f0"
TEXT_DIM     = "#b0b0b0"
TEXT_MUTED   = "#606060"

BORDER       = "#303030"
BORDER_HOVER = "#787878"
BORDER_FOCUS = "#aaaaaa"
BORDER_SUBTLE = "#282828"

SEP          = "#1e1e1e"

ACTIVE_BG    = "#ffffff"
ACTIVE_TEXT  = "#000000"

RADIUS       = "4px"
RADIUS_LG    = "6px"

_base_font   = 16


def _qss():
    b = _base_font
    return f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-size: {b}px;
}}

QMainWindow {{
    background-color: {BG_SIDEBAR};
}}

/* ── Sidebar ── */

QWidget#sidebar {{
    background-color: {BG_SIDEBAR};
}}

QLabel#appTitle {{
    color: {TEXT_BRIGHT};
    font-size: {b+2}px;
    font-weight: 700;
    padding: 0 4px;
    background: transparent;
}}

QPushButton#navBtn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    color: {TEXT_MUTED};
    font-size: {b-1}px;
    font-weight: 500;
    text-align: left;
    padding: 9px 14px;
    min-height: 22px;
    min-width: 0;
}}

QPushButton#navBtn:hover {{
    background: {BG_HOVER};
    color: {TEXT_DIM};
}}

QPushButton#navBtn:checked {{
    background: {ACTIVE_BG};
    color: {ACTIVE_TEXT};
    font-weight: 600;
}}

QFrame#sidebarLine {{
    background: {SEP};
    border: none;
    max-width: 1px;
}}

/* ── Content labels ── */

QLabel {{
    background: transparent;
    color: {TEXT};
}}

QLabel#pageTitle {{
    font-size: {b+6}px;
    font-weight: 600;
    color: {TEXT_BRIGHT};
}}

QLabel#sectionTitle {{
    font-size: {b}px;
    font-weight: 600;
    color: {TEXT_DIM};
    padding-top: 2px;
    padding-bottom: 2px;
}}

QLabel#detailTitle {{
    font-size: {b+2}px;
    font-weight: 600;
    color: {TEXT_BRIGHT};
}}

QLabel#statusLabel {{
    color: {TEXT_MUTED};
    font-size: {b}px;
}}

QLabel#fieldLabel {{
    color: {TEXT_DIM};
}}

/* ── Buttons ── */

QPushButton {{
    background-color: {BG};
    color: #cccccc;
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 5px 12px;
    min-height: 26px;
    min-width: 60px;
}}

QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER_HOVER};
    color: {TEXT_BRIGHT};
}}

QPushButton:pressed {{
    background-color: {BG_PRESS};
    border-color: {BORDER};
    color: #aaaaaa;
}}

QPushButton:disabled {{
    color: #383838;
    background-color: {BG};
    border-color: {BORDER_SUBTLE};
}}

QPushButton:checked {{
    background-color: {ACTIVE_BG};
    color: {ACTIVE_TEXT};
    border-color: {ACTIVE_BG};
}}

/* ── Lists ── */

QListWidget {{
    background: {BG_RAISED};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: {RADIUS_LG};
    outline: none;
    padding: 3px;
}}

QListWidget::item {{
    padding: 8px 10px;
    border-radius: 5px;
    color: #c8c8c8;
}}

QListWidget::item:selected {{
    background: {ACTIVE_BG};
    color: {ACTIVE_TEXT};
}}

QListWidget::item:hover:!selected {{
    background: {BG_HOVER};
}}

/* ── Separators ── */

QFrame[frameShape="4"] {{
    border: none;
    background-color: {SEP};
    max-height: 1px;
    margin: 2px 0;
}}

QFrame[frameShape="5"] {{
    border: none;
    background-color: {SEP};
    max-width: 1px;
}}

/* ── Checkboxes ── */

QCheckBox {{
    spacing: 8px;
    color: #cccccc;
}}

QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {BG};
}}

QCheckBox::indicator:checked {{
    background-color: {ACTIVE_BG};
    border-color: {ACTIVE_BG};
}}

QCheckBox::indicator:hover {{
    border-color: {BORDER_FOCUS};
}}

/* ── Inputs ── */

QComboBox {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 4px 10px;
    min-height: 26px;
    color: #d0d0d0;
}}

QComboBox:hover {{ border-color: {BORDER_HOVER}; }}
QComboBox:focus {{ border-color: {BORDER_FOCUS}; }}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    selection-background-color: {ACTIVE_BG};
    selection-color: {ACTIVE_TEXT};
    outline: none;
    padding: 3px;
}}

QComboBox QAbstractItemView::item:hover {{
    background: {BG_HOVER};
}}

QSpinBox, QDoubleSpinBox {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 4px 8px;
    min-height: 26px;
    color: #d0d0d0;
}}

QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {BORDER_FOCUS}; }}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {BG_HOVER};
    border: none;
    width: 18px;
}}

QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: #252525;
}}

QLineEdit {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 4px 10px;
    color: {TEXT_BRIGHT};
    min-height: 26px;
}}

QLineEdit:focus {{ border-color: {BORDER_FOCUS}; }}

/* ── Sliders ── */

QSlider::groove:horizontal {{
    height: 3px;
    background: #2e2e2e;
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: #d0d0d0;
    border: none;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -6px 0;
}}

QSlider::handle:horizontal:hover {{ background: {ACTIVE_BG}; }}

QSlider::sub-page:horizontal {{
    background: {BORDER_HOVER};
    border-radius: 2px;
}}

/* ── Scrollbars ── */

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 4px 0;
}}

QScrollBar::handle:vertical {{
    background: #2a2a2a;
    border-radius: 3px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{ background: {BORDER}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollArea {{
    border: none;
    background: transparent;
}}

/* ── Dialogs ── */

QInputDialog, QMessageBox {{ background: {BG}; }}
QMessageBox QLabel, QInputDialog QLabel {{ background: transparent; color: {TEXT}; }}
"""


_PAGES = [
    ("Wi-Fi",       "network-wireless",                         WifiTab),
    ("Bluetooth",   "bluetooth",                                BluetoothTab),
    ("Displays",    "video-display",                            DisplaysTab),
    ("Sound",       "audio-volume-high",                        SoundTab),
    ("Apps",        "preferences-desktop-default-applications", AppsTab),
    ("Appearance",  "preferences-desktop-theme",                AppearanceTab),
    ("System",      "preferences-system",                       SystemTab),
]

_TAB_FLAGS = [
    ({"--wifi"},                          0),
    ({"--bluetooth"},                     1),
    ({"--displays"},                      2),
    ({"--sound"},                         3),
    ({"--apps"},                          4),
    ({"--appearance", "--appearence"},    5),
    ({"--system"},                        6),
]


def main():
    if not _acquire_lock():
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setFont(QFont("sans", 16))
    app.setStyleSheet(_qss())

    window = QMainWindow()
    window.setWindowTitle("Settings")
    window.setMinimumSize(960, 620)

    # Root layout: sidebar | line | stack
    root_widget = QWidget()
    root = QHBoxLayout(root_widget)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # Sidebar
    sidebar = QWidget()
    sidebar.setObjectName("sidebar")
    sidebar.setFixedWidth(215)
    sb = QVBoxLayout(sidebar)
    sb.setContentsMargins(14, 28, 14, 28)
    sb.setSpacing(3)

    title_lbl = QLabel("Settings")
    title_lbl.setObjectName("appTitle")
    sb.addWidget(title_lbl)
    sb.addSpacing(18)

    stack = QStackedWidget()
    btn_group = QButtonGroup()
    btn_group.setExclusive(True)

    def _goto(idx):
        stack.setCurrentIndex(idx)
        btn_group.button(idx).setChecked(True)

    for i, (label, icon_name, PageClass) in enumerate(_PAGES):
        stack.addWidget(PageClass())

        btn = QPushButton(f"  {label}")
        btn.setObjectName("navBtn")
        btn.setCheckable(True)
        icon = QIcon.fromTheme(icon_name)
        if not icon.isNull():
            btn.setIcon(icon)
            btn.setIconSize(QSize(16, 16))
        btn.clicked.connect(lambda _, idx=i: _goto(idx))
        btn_group.addButton(btn, i)
        sb.addWidget(btn)

    sb.addStretch()

    root.addWidget(sidebar)

    line = QFrame()
    line.setObjectName("sidebarLine")
    line.setFrameShape(QFrame.VLine)
    line.setFixedWidth(1)
    root.addWidget(line)

    content = QWidget()
    cl = QVBoxLayout(content)
    cl.setContentsMargins(0, 12, 0, 0)
    cl.setSpacing(0)
    cl.addWidget(stack)
    root.addWidget(content, stretch=1)
    window.setCentralWidget(root_widget)

    # Initial tab from CLI args
    initial = 0
    argv = set(sys.argv[1:])
    for flags, idx in _TAB_FLAGS:
        if flags & argv:
            initial = idx
            break
    _goto(initial)

    # Alt+N shortcuts
    for i in range(len(_PAGES)):
        QShortcut(QKeySequence(f"Alt+{i + 1}"), window).activated.connect(
            lambda idx=i: _goto(idx)
        )

    # Zoom
    def zoom(delta):
        global _base_font
        _base_font = max(10, min(32, _base_font + delta))
        app.setStyleSheet(_qss())

    QShortcut(QKeySequence("Ctrl+="), window).activated.connect(lambda: zoom(1))
    QShortcut(QKeySequence("Ctrl++"), window).activated.connect(lambda: zoom(1))
    QShortcut(QKeySequence("Ctrl+-"), window).activated.connect(lambda: zoom(-1))
    QShortcut(QKeySequence("Ctrl+0"), window).activated.connect(lambda: zoom(16 - _base_font))

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
