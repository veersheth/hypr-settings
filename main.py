import configparser
import fcntl
import os
import subprocess
import sys
import tempfile
from PySide6.QtCore import QSize
from PySide6.QtGui import QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QPushButton, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from wifi_tab import WifiTab
from bluetooth_tab import BluetoothTab
from displays_tab import DisplaysTab
from sound_tab import SoundTab
from apps_tab import AppsTab
from appearance_tab import AppearanceTab
from system_tab import SystemTab

_LOCK_FILE = os.path.join(tempfile.gettempdir(), f"hypr-settings-{os.getenv('USER', 'user')}.lock")
_lock_fh   = None
_is_dark   = True
_base_font = 16


def _acquire_lock():
    global _lock_fh
    _lock_fh = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _detect_dark():
    try:
        r = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True, text=True, timeout=2,
        )
        val = r.stdout.strip().strip("'\"")
        if val == "prefer-light":
            return False
        if val == "prefer-dark":
            return True
    except Exception:
        pass
    try:
        cp = configparser.RawConfigParser()
        cp.read(os.path.expanduser("~/.config/gtk-3.0/settings.ini"))
        val = cp.get("Settings", "gtk-application-prefer-dark-theme", fallback="1")
        return val.lower() not in ("0", "false")
    except Exception:
        pass
    return True


def _qss():
    b = _base_font

    if _is_dark:
        BG            = "#0d0d0d"
        BG_SIDEBAR    = "#080808"
        BG_RAISED     = "#111111"
        BG_HOVER      = "#1a1a1a"
        BG_PRESS      = "#050505"
        TEXT          = "#d8d8d8"
        TEXT_BRIGHT   = "#f0f0f0"
        TEXT_DIM      = "#b0b0b0"
        TEXT_MUTED    = "#606060"
        BORDER        = "#303030"
        BORDER_HOVER  = "#787878"
        BORDER_FOCUS  = "#5a9cf8"
        BORDER_SUBTLE = "#282828"
        SEP           = "#1e1e1e"
        INPUT_TEXT    = "#d0d0d0"
        LIST_ITEM     = "#c8c8c8"
    else:
        BG            = "#f5f5f5"
        BG_SIDEBAR    = "#eaeaea"
        BG_RAISED     = "#ffffff"
        BG_HOVER      = "#e4e4e4"
        BG_PRESS      = "#d4d4d4"
        TEXT          = "#1c1c1c"
        TEXT_BRIGHT   = "#0a0a0a"
        TEXT_DIM      = "#555555"
        TEXT_MUTED    = "#888888"
        BORDER        = "#c8c8c8"
        BORDER_HOVER  = "#999999"
        BORDER_FOCUS  = "#3b82f6"
        BORDER_SUBTLE = "#e0e0e0"
        SEP           = "#dedede"
        INPUT_TEXT    = "#1c1c1c"
        LIST_ITEM     = "#2a2a2a"

    ACCENT      = "#3b82f6"
    ACCENT_TEXT = "#ffffff"
    RADIUS      = "4px"
    RADIUS_LG   = "6px"

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
    font-size: {b}px;
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
    background: {ACCENT};
    color: {ACCENT_TEXT};
    font-weight: 600;
    border-radius: 6px;
}}

QSplitter::handle {{
    background: {SEP};
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
    color: {TEXT};
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
    color: {TEXT_DIM};
}}

QPushButton:disabled {{
    color: {TEXT_MUTED};
    background-color: {BG};
    border-color: {BORDER_SUBTLE};
}}

QPushButton:checked {{
    background-color: {ACCENT};
    color: {ACCENT_TEXT};
    border-color: {ACCENT};
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
    padding: 12px 14px;
    border-radius: 5px;
    color: {LIST_ITEM};
}}

QListWidget::item:selected {{
    background: {ACCENT};
    color: {ACCENT_TEXT};
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
    color: {TEXT};
}}

QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {BG};
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
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
    color: {INPUT_TEXT};
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
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
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
    color: {INPUT_TEXT};
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
    background: {BG_PRESS};
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
    background: {BORDER_SUBTLE};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: {TEXT_DIM};
    border: none;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -6px 0;
}}

QSlider::handle:horizontal:hover {{ background: {ACCENT}; }}

QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}

/* ── Scrollbars ── */

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 4px 0;
}}

QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 3px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{ background: {BORDER_HOVER}; }}
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
    global _is_dark

    if not _acquire_lock():
        sys.exit(0)

    _is_dark = _detect_dark()

    app = QApplication(sys.argv)
    app.setFont(QFont("sans", 16))
    app.setStyleSheet(_qss())

    import common
    def _apply_theme(dark: bool):
        global _is_dark
        _is_dark = dark
        app.setStyleSheet(_qss())
    common.on_theme_change = _apply_theme

    window = QMainWindow()
    window.setWindowTitle("Settings")
    window.setMinimumSize(960, 620)

    root_widget = QWidget()
    root = QHBoxLayout(root_widget)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    splitter = QSplitter()
    splitter.setHandleWidth(1)

    # Sidebar
    sidebar = QWidget()
    sidebar.setObjectName("sidebar")
    sidebar.setMinimumWidth(160)
    sidebar.setMaximumWidth(400)
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

    content = QWidget()
    cl = QVBoxLayout(content)
    cl.setContentsMargins(0, 32, 0, 0)
    cl.setSpacing(0)
    cl.addWidget(stack)

    splitter.addWidget(sidebar)
    splitter.addWidget(content)
    splitter.setSizes([260, 700])
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)

    root.addWidget(splitter)
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
