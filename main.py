import sys
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from wifi_tab import WifiTab
from bluetooth_tab import BluetoothTab
from displays_tab import DisplaysTab
from sound_tab import SoundTab
from system_tab import SystemTab

BG          = "#0d0d0d"   # primary background
BG_RAISED   = "#111111"   # inputs, list, slightly lifted surfaces
BG_HOVER    = "#1a1a1a"   # hover state background
BG_PRESS    = "#080808"   # pressed state background

TEXT        = "#d8d8d8"   # default text
TEXT_BRIGHT = "#f0f0f0"   # headings, active labels
TEXT_DIM    = "#b0b0b0"   # section titles, secondary info
TEXT_MUTED  = "#707070"   # status labels, placeholders
BORDER      = "#545454"   # default border (buttons, inputs)
BORDER_HOVER = "#787878"  # border on hover
BORDER_FOCUS = "#aaaaaa"  # border on focus
BORDER_SUBTLE = "#282828" # list widget border, disabled

SEP         = "#232323"   # separator lines

ACTIVE_BG   = "#ffffff"   # selected tab / list item background
ACTIVE_TEXT = "#000000"   # text on ACTIVE_BG

RADIUS      = "4px"       # standard border radius
RADIUS_LG   = "6px"       # larger radius (list widget)

_base_font  = 16          # zoom base (px), changed by Ctrl+/Ctrl+-

def _qss():
    b = _base_font
    return f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-size: {b}px;
}}

QMainWindow {{
    background-color: {BG};
}}

QTabWidget::pane {{
    border: none;
    background-color: {BG};
}}

QTabBar {{
    background: {BG};
}}

QTabBar::tab {{
    background: {BG};
    color: {TEXT_MUTED};
    padding: 10px 28px;
    border: none;
    min-width: 80px;
}}

QTabBar::tab:selected {{
    background: {ACTIVE_BG};
    color: {ACTIVE_TEXT};
}}

QTabBar::tab:hover:!selected {{
    color: {TEXT_DIM};
    background: {BG_HOVER};
}}

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

QPushButton {{
    background-color: {BG};
    color: #cccccc;
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 5px 5px;
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

QComboBox {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 4px 10px;
    min-height: 26px;
    color: #d0d0d0;
}}

QComboBox:hover {{
    border-color: {BORDER_HOVER};
}}

QComboBox:focus {{
    border-color: {BORDER_FOCUS};
}}

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

QSpinBox {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 4px 8px;
    min-height: 26px;
    color: #d0d0d0;
}}

QSpinBox:focus {{
    border-color: {BORDER_FOCUS};
}}

QSpinBox::up-button, QSpinBox::down-button {{
    background: {BG_HOVER};
    border: none;
    width: 18px;
}}

QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: #252525;
}}

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

QSlider::handle:horizontal:hover {{
    background: {ACTIVE_BG};
}}

QSlider::sub-page:horizontal {{
    background: {BORDER_HOVER};
    border-radius: 2px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 4px 0;
}}

QScrollBar::handle:vertical {{
    background: #333333;
    border-radius: 3px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: {BORDER};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QLineEdit {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 4px 10px;
    color: {TEXT_BRIGHT};
    min-height: 26px;
}}

QLineEdit:focus {{
    border-color: {BORDER_FOCUS};
}}

QInputDialog, QMessageBox {{
    background: {BG};
}}

QMessageBox QLabel, QInputDialog QLabel {{
    background: transparent;
    color: {TEXT};
}}

QScrollArea {{
    border: none;
    background: transparent;
}}
"""


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Sans", 16))
    app.setStyleSheet(_qss())

    window = QMainWindow()
    window.setWindowTitle("Settings")
    window.setMinimumSize(880, 580)

    tabs = QTabWidget()

    tabs.addTab(WifiTab(), "Wi-Fi")
    tabs.addTab(BluetoothTab(), "Bluetooth")
    tabs.addTab(DisplaysTab(), "Displays")
    tabs.addTab(SoundTab(), "Sound")
    tabs.addTab(SystemTab(), "System")

    for i in range(tabs.count()):
        QShortcut(QKeySequence(f"Alt+{i + 1}"), window).activated.connect(
            lambda idx=i: tabs.setCurrentIndex(idx)
        )

    def zoom(delta):
        global _base_font
        _base_font = max(10, min(32, _base_font + delta))
        app.setStyleSheet(_qss())

    QShortcut(QKeySequence("Ctrl+="), window).activated.connect(lambda: zoom(1))
    QShortcut(QKeySequence("Ctrl++"), window).activated.connect(lambda: zoom(1))
    QShortcut(QKeySequence("Ctrl+-"), window).activated.connect(lambda: zoom(-1))
    QShortcut(QKeySequence("Ctrl+0"), window).activated.connect(lambda: zoom(16 - _base_font))

    window.setCentralWidget(tabs)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
