import subprocess
from PySide6.QtCore import QEasingCurve, QEvent, Property, QPropertyAnimation, Qt, Signal

on_theme_change = None  # set by main.py to (dark: bool) -> None
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
        self._pos = 0.0  # 0.0 = left (off), 1.0 = right (on)
        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"handle_pos", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

    def _get_pos(self):
        return self._pos

    def _set_pos(self, val):
        self._pos = val
        self.update()

    handle_pos = Property(float, _get_pos, _set_pos)

    def set_on(self, on, silent=False):
        self._on = on
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()
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
        # Interpolate track: #2e2e2e (off) -> #a3b3d4 (on)
        t = self._pos
        tr = int(46  + t * (163 - 46))
        tg = int(46  + t * (179 - 46))
        tb = int(46  + t * (212 - 46))
        p.setBrush(QColor(tr, tg, tb))
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)
        m = 3
        d = h - 2 * m
        hx = int(m + self._pos * (w - 2 * m - d))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(hx, m, d, d)
        p.end()


class NavList(QListWidget):
    """QListWidget with j/k navigation."""
    _KEY_MAP = {Qt.Key_J: Qt.Key_Down, Qt.Key_K: Qt.Key_Up}

    def keyPressEvent(self, e):
        mapped = self._KEY_MAP.get(e.key())
        if mapped is not None:
            e = QKeyEvent(QEvent.KeyPress, mapped, e.modifiers())
        super().keyPressEvent(e)
