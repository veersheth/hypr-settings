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
    }
"""

def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Sans", 11))
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
