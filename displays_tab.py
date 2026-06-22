import json
from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)
from common import run, separator, make_centered

COLORS = ["#2a5298", "#7b2d8b", "#1e7a4a", "#8b4513", "#1a6b8a", "#6b1a3a"]


def _load_monitors():
    out, ok = run(["hyprctl", "monitors", "all", "-j"])
    if not ok or not out:
        return None, "hyprctl not available — are you running Hyprland?"
    try:
        monitors = json.loads(out)
    except json.JSONDecodeError:
        return None, "Failed to parse hyprctl output"

    # Normalize mirrorOf ("none" string → None, name → name)
    for m in monitors:
        raw = m.get("mirrorOf", "none")
        m["mirror"] = None if raw == "none" else raw
    return monitors, None


def _apply_monitor(m):
    value = (
        f"{m['name']},"
        f"{m['width']}x{m['height']}@{m['refreshRate']:.2f},"
        f"{m['x']}x{m['y']},"
        f"{m.get('scale', 1.0)},"
        f"transform,{m.get('transform', 0)}"
    )
    if m.get("mirror"):
        value += f",mirror,{m['mirror']}"
    return run(["hyprctl", "keyword", "monitor", value])


def _logical_size(m):
    s = m.get("scale", 1.0) or 1.0
    return int(m["width"] / s), int(m["height"] / s)


# canvas

class _MonitorCanvas(QWidget):
    monitor_selected = Signal(object)
    monitor_moved = Signal(int, int)

    PAD = 24

    def __init__(self):
        super().__init__()
        self._monitors = []
        self._sel = -1
        self._drag = -1
        self._drag_off = QPoint()
        self._scale = 0.1
        self._min_x = 0
        self._min_y = 0
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_monitors(self, monitors):
        self._monitors = monitors
        self._sel = -1
        self._recompute()
        self.update()

    def _recompute(self):
        if not self._monitors:
            return
        lw = [_logical_size(m)[0] for m in self._monitors]
        lh = [_logical_size(m)[1] for m in self._monitors]
        self._min_x = min(m["x"] for m in self._monitors)
        self._min_y = min(m["y"] for m in self._monitors)
        total_w = max(m["x"] + w for m, w in zip(self._monitors, lw)) - self._min_x
        total_h = max(m["y"] + h for m, h in zip(self._monitors, lh)) - self._min_y
        avail_w = max(self.width() - 2 * self.PAD, 1)
        avail_h = max(self.height() - 2 * self.PAD, 1)
        if total_w > 0 and total_h > 0:
            self._scale = min(avail_w / total_w, avail_h / total_h)

    def _rect(self, m):
        lw, lh = _logical_size(m)
        x = int((m["x"] - self._min_x) * self._scale) + self.PAD
        y = int((m["y"] - self._min_y) * self._scale) + self.PAD
        return QRect(x, y, max(int(lw * self._scale), 20), max(int(lh * self._scale), 20))

    def _to_logical(self, p):
        return (
            max(0, int((p.x() - self.PAD) / self._scale) + self._min_x),
            max(0, int((p.y() - self.PAD) / self._scale) + self._min_y),
        )

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#080808"))
        for i, m in enumerate(self._monitors):
            rect = self._rect(m)
            color = QColor(COLORS[i % len(COLORS)])
            if i == self._sel:
                color = color.lighter(155)
            p.fillRect(rect, color)
            p.setPen(QColor("#ffffff"))
            lw, lh = _logical_size(m)
            label = f"{m['name']}\n{lw}×{lh}"
            if m.get("mirror"):
                label += f"\n⟶ {m['mirror']}"
            p.drawText(rect, Qt.AlignCenter, label)
        p.end()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        for i in range(len(self._monitors) - 1, -1, -1):
            if self._rect(self._monitors[i]).contains(e.pos()):
                self._sel = i
                self._drag = i
                self._drag_off = e.pos() - self._rect(self._monitors[i]).topLeft()
                self.monitor_selected.emit(self._monitors[i])
                self.update()
                return
        self._sel = -1
        self.monitor_selected.emit(None)
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag < 0:
            return
        rx, ry = self._to_logical(e.pos() - self._drag_off)
        self._monitors[self._drag]["x"] = rx
        self._monitors[self._drag]["y"] = ry
        self.monitor_moved.emit(rx, ry)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = -1

    def resizeEvent(self, _):
        self._recompute()
        self.update()


# settings 

class _SettingsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._monitor = None
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 4, 0, 0)
        root.setSpacing(8)
        root.setAlignment(Qt.AlignTop)

        self._name_lbl = QLabel()
        self._name_lbl.setObjectName("detailTitle")
        root.addWidget(self._name_lbl)

        self._desc_lbl = QLabel()
        self._desc_lbl.setWordWrap(True)
        root.addWidget(self._desc_lbl)

        root.addWidget(separator())

        def row(label, widget):
            h = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(110)
            lbl.setObjectName("fieldLabel")
            h.addWidget(lbl)
            h.addWidget(widget, stretch=1)
            root.addLayout(h)

        self._pos_x = QSpinBox()
        self._pos_x.setRange(-99999, 99999)
        self._pos_x.valueChanged.connect(self._on_pos)
        row("Position X", self._pos_x)

        self._pos_y = QSpinBox()
        self._pos_y.setRange(-99999, 99999)
        self._pos_y.valueChanged.connect(self._on_pos)
        row("Position Y", self._pos_y)

        root.addWidget(separator())

        self._mirror_cb = QComboBox()
        self._mirror_cb.currentIndexChanged.connect(self._on_mirror)
        row("Mirror", self._mirror_cb)

        root.addStretch()
        self.setVisible(False)

    def show_monitor(self, m, all_monitors=None):
        self._monitor = m
        self._busy = True

        self._name_lbl.setText(m["name"])
        desc = m.get("description", "")
        self._desc_lbl.setText(desc)
        self._desc_lbl.setVisible(bool(desc))

        self._pos_x.setValue(m.get("x", 0))
        self._pos_y.setValue(m.get("y", 0))

        self._mirror_cb.clear()
        self._mirror_cb.addItem("None (extend)", None)
        for other in (all_monitors or []):
            if other["name"] != m["name"]:
                self._mirror_cb.addItem(other["name"], other["name"])
        current_mirror = m.get("mirror")
        idx = self._mirror_cb.findData(current_mirror)
        self._mirror_cb.setCurrentIndex(idx if idx >= 0 else 0)

        self._set_position_enabled(not bool(current_mirror))
        self._busy = False
        self.setVisible(True)

    def update_position(self, x, y):
        """Keep spinboxes in sync while the user drags on the canvas."""
        self._busy = True
        self._pos_x.setValue(x)
        self._pos_y.setValue(y)
        self._busy = False

    def _set_position_enabled(self, enabled):
        self._pos_x.setEnabled(enabled)
        self._pos_y.setEnabled(enabled)

    def _on_pos(self):
        if not self._busy and self._monitor:
            self._monitor["x"] = self._pos_x.value()
            self._monitor["y"] = self._pos_y.value()

    def _on_mirror(self, idx):
        if self._busy or not self._monitor:
            return
        target = self._mirror_cb.itemData(idx)
        self._monitor["mirror"] = target
        self._set_position_enabled(not bool(target))


# main tab

class DisplaysTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(make_centered(self))
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Displays")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._apply)
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.clicked.connect(self._load)
        header.addWidget(self._apply_btn)
        header.addWidget(self._reload_btn)
        root.addLayout(header)

        self._status_lbl = QLabel("Loading…")
        self._status_lbl.setObjectName("statusLabel")
        root.addWidget(self._status_lbl)

        body = QHBoxLayout()
        body.setSpacing(0)

        canvas_wrap = QVBoxLayout()
        canvas_wrap.setContentsMargins(0, 0, 16, 0)
        self._canvas = _MonitorCanvas()
        self._canvas.monitor_selected.connect(self._on_select)
        self._canvas.monitor_moved.connect(self._on_monitor_moved)
        canvas_wrap.addWidget(self._canvas)
        body.addLayout(canvas_wrap, stretch=3)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        body.addWidget(sep)

        self._settings = _SettingsPanel()
        body.addWidget(self._settings, stretch=2)

        root.addLayout(body, stretch=1)

    def _load(self):
        monitors, err = _load_monitors()
        if err:
            self._status_lbl.setText(f"Error: {err}")
            return
        self._canvas.set_monitors(monitors)
        self._settings.setVisible(False)
        n = len(monitors)
        self._status_lbl.setText(f"{n} display(s) detected — drag to arrange, click to configure")

    def _on_select(self, monitor):
        if monitor:
            self._settings.show_monitor(monitor, self._canvas._monitors)
        else:
            self._settings.setVisible(False)

    def _on_monitor_moved(self, x, y):
        self._settings.update_position(x, y)

    def _apply(self):
        monitors = self._canvas._monitors
        if not monitors:
            return
        failed = []
        for m in monitors:
            _, ok = _apply_monitor(m)
            if not ok:
                failed.append(m["name"])
        if failed:
            self._status_lbl.setText(f"Failed to apply: {', '.join(failed)}")
        else:
            self._status_lbl.setText("Settings applied")
        self._load()
