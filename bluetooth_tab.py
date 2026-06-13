from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout


class BluetoothTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("bluetooth tab"))
