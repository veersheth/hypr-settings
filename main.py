import sys
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from wifi_tab import WifiTab
from bluetooth_tab import BluetoothTab
from displays_tab import DisplaysTab

QSS = """
* {
    background-color: #141414;
    color: #ffffff;
    font-size: 18px;
    border: none;
}

QMainWindow, QWidget {
    background-color: #141414;
}

QTabWidget::pane {
    border: 1px solid #4f4f4f;
}

QTabBar::tab {
    background-color: #141414;
    color: #ffffff;
    padding: 8px 20px;
    border: 1px solid #4f4f4f;
    border-bottom: none;
}

QTabBar::tab:selected {
    background-color: #cccccc;
    color: #000000;
}

QTabBar::tab:hover:!selected {
    background-color: #1a1a1a;
}

QPushButton {
    background-color: #1e1e1e;
    color: #ffffff;
    border: 1px solid #4f4f4f;
    padding: 6px 16px;
}

QPushButton:hover {
    background-color: #2a2a2a;
}

QPushButton:pressed {
    background-color: #111111;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background-color: #1e1e1e;
    color: #ffffff;
    border: 1px solid #4f4f4f;
    padding: 4px 8px;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #1e1e1e;
    color: #ffffff;
    border: 1px solid #4f4f4f;
    selection-background-color: #2a2a2a;
}

QScrollBar:vertical {
    background-color: #1a1a1a;
    width: 10px;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #4f4f4f;
    min-height: 20px;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #1a1a1a;
    height: 10px;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: #4f4f4f;
    min-width: 20px;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
"""


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Sans", 14))
    app.setStyleSheet(QSS)

    window = QMainWindow()
    window.setWindowTitle("Setting Settings")

    tabs = QTabWidget()
    tabs.addTab(WifiTab(), "Wi-Fi")
    tabs.addTab(BluetoothTab(), "Bluetooth")
    tabs.addTab(DisplaysTab(), "Displays")

    window.setCentralWidget(tabs)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
