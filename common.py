import subprocess
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QFrame, QListWidget


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "", False


def separator():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFixedHeight(1)
    return f


class NavList(QListWidget):
    """QListWidget with j/k navigation."""
    _KEY_MAP = {Qt.Key_J: Qt.Key_Down, Qt.Key_K: Qt.Key_Up}

    def keyPressEvent(self, e):
        mapped = self._KEY_MAP.get(e.key())
        if mapped is not None:
            e = QKeyEvent(QEvent.KeyPress, mapped, e.modifiers())
        super().keyPressEvent(e)
