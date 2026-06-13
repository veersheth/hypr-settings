from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout


class DisplaysTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("displays tab"))
