import subprocess
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QListWidget, QWidget


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


def make_centered(host, max_width=1100):
    """Wrap host's layout in a centered container with a max width."""
    outer = QHBoxLayout(host)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    inner = QWidget()
    inner.setMaximumWidth(max_width)
    outer.addStretch()
    outer.addWidget(inner, stretch=1)
    outer.addStretch()
    return inner


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    _W, _H = 48, 24

    def __init__(self):
        super().__init__()
        self._on = False
        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.PointingHandCursor)

    def set_on(self, on, silent=False):
        self._on = on
        self.update()
        if not silent:
            self.toggled.emit(on)

    def is_on(self):
        return self._on

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.set_on(not self._on)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self._W, self._H
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2e2e2e"))
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)
        m = 3
        d = h - 2 * m
        p.setBrush(QColor("#d8d8d8"))
        p.drawEllipse((w - m - d) if self._on else m, m, d, d)
        p.end()


class NavList(QListWidget):
    """QListWidget with j/k navigation."""
    _KEY_MAP = {Qt.Key_J: Qt.Key_Down, Qt.Key_K: Qt.Key_Up}

    def keyPressEvent(self, e):
        mapped = self._KEY_MAP.get(e.key())
        if mapped is not None:
            e = QKeyEvent(QEvent.KeyPress, mapped, e.modifiers())
        super().keyPressEvent(e)
