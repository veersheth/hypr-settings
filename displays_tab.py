import json
import subprocess
from PySide6.QtCore import Qt, QRect, QPoint, QSize, Signal
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

COLORS = ["#2a5298", "#7b2d8b", "#1e7a4a", "#8b4513", "#1a6b8a", "#6b1a3a"]
TRANSFORMS = {0: "Normal", 1: "90°", 2: "180°", 3: "270°"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip(), r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "", False


def _load_monitors():
    out, ok = _run(["hyprctl", "monitors", "all", "-j"])
    if not ok or not out:
        return None, "hyprctl not available — are you running Hyprland?"
    try:
        return json.loads(out), None
    except json.JSONDecodeError:
        return None, "Failed to parse hyprctl output"


def _parse_mode(mode_str):
    """'2560x1440@165.00Hz' -> (2560, 1440, 165.0) or None"""
    try:
        res, hz = mode_str.rstrip("Hz").split("@")
        w, h = res.split("x")
        return int(w), int(h), float(hz)
    except (ValueError, AttributeError):
        return None


def _apply_monitor(m):
    if m.get("disabled"):
        return _run(["hyprctl", "dispatch", "dpms", "off", m["name"]])
    else:
        transform = m.get("transform", 0)
        value = (
            f"{m['name']},"
            f"{m['width']}x{m['height']}@{m['refreshRate']:.2f},"
            f"{m['x']}x{m['y']},"
            f"{m.get('scale', 1.0)},"
            f"transform,{transform}"
        )
        if m.get("mirror"):
            value += f",mirror,{m['mirror']}"
        _run(["hyprctl", "dispatch", "dpms", "on", m["name"]])
        return _run(["hyprctl", "keyword", "monitor", value])


def _separator():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    return f


def _logical_size(m):
    s = m.get("scale", 1.0) or 1.0
    return int(m["width"] / s), int(m["height"] / s)


# ── canvas ────────────────────────────────────────────────────────────────────

class _MonitorCanvas(QWidget):
    monitor_selected = Signal(object)

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
        p.fillRect(self.rect(), QColor("#1c1c1c"))
        for i, m in enumerate(self._monitors):
            rect = self._rect(m)
            color = QColor(COLORS[i % len(COLORS)])
            if i == self._sel:
                color = color.lighter(155)
            p.fillRect(rect, color)
            p.setPen(QColor("#ffffff"))
            lw, lh = _logical_size(m)
            text = f"{m['name']}\n{lw}×{lh}"
            if m.get("disabled"):
                text += "\n(disabled)"
            p.drawText(rect, Qt.AlignCenter, text)
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
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = -1

    def resizeEvent(self, _):
        self._recompute()
        self.update()


# ── settings panel ────────────────────────────────────────────────────────────

class _SettingsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._monitor = None
        self._busy = False
        self._modes = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 0, 0, 0)
        root.setSpacing(8)
        root.setAlignment(Qt.AlignTop)

        self._name_lbl = QLabel()
        self._name_lbl.setStyleSheet("font-weight: bold; font-size: 16px;")
        root.addWidget(self._name_lbl)

        self._desc_lbl = QLabel()
        self._desc_lbl.setWordWrap(True)
        root.addWidget(self._desc_lbl)

        root.addWidget(_separator())

        def row(label, widget):
            h = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(110)
            h.addWidget(lbl)
            h.addWidget(widget, stretch=1)
            root.addLayout(h)

        self._res_cb = QComboBox()
        self._res_cb.currentIndexChanged.connect(self._on_res)
        row("Resolution", self._res_cb)

        self._hz_cb = QComboBox()
        self._hz_cb.currentIndexChanged.connect(self._on_hz)
        row("Refresh rate", self._hz_cb)

        root.addWidget(_separator())

        self._scale_sb = QDoubleSpinBox()
        self._scale_sb.setRange(0.25, 4.0)
        self._scale_sb.setSingleStep(0.25)
        self._scale_sb.setDecimals(2)
        self._scale_sb.valueChanged.connect(self._on_scale)
        row("Scale", self._scale_sb)

        self._rot_cb = QComboBox()
        for label in TRANSFORMS.values():
            self._rot_cb.addItem(label)
        self._rot_cb.currentIndexChanged.connect(self._on_rot)
        row("Rotation", self._rot_cb)

        root.addWidget(_separator())

        self._pos_x = QSpinBox()
        self._pos_x.setRange(-99999, 99999)
        self._pos_x.valueChanged.connect(self._on_pos)
        row("Position X", self._pos_x)

        self._pos_y = QSpinBox()
        self._pos_y.setRange(-99999, 99999)
        self._pos_y.valueChanged.connect(self._on_pos)
        row("Position Y", self._pos_y)

        root.addWidget(_separator())

        self._mirror_cb = QComboBox()
        self._mirror_cb.currentIndexChanged.connect(self._on_mirror)
        row("Mirror", self._mirror_cb)

        root.addWidget(_separator())

        self._vrr_cb = QCheckBox("Variable Refresh Rate (VRR/Adaptive Sync)")
        self._vrr_cb.stateChanged.connect(self._on_vrr)
        root.addWidget(self._vrr_cb)

        self._disabled_cb = QCheckBox("Disable this display")
        self._disabled_cb.stateChanged.connect(self._on_disabled)
        root.addWidget(self._disabled_cb)

        root.addStretch()
        self.setVisible(False)

    def show_monitor(self, m, all_monitors=None):
        self._monitor = m
        self._modes = m.get("availableModes", [])
        self._busy = True

        self._name_lbl.setText(m["name"])
        desc = m.get("description", "")
        self._desc_lbl.setText(desc)
        self._desc_lbl.setVisible(bool(desc))

        # Resolutions — deduplicate, preserve order
        seen, resolutions = set(), []
        for mode in self._modes:
            parsed = _parse_mode(mode)
            if parsed:
                key = (parsed[0], parsed[1])
                if key not in seen:
                    seen.add(key)
                    resolutions.append(key)

        self._res_cb.clear()
        for w, h in resolutions:
            self._res_cb.addItem(f"{w}×{h}", (w, h))

        cur = self._res_cb.findText(f"{m['width']}×{m['height']}")
        self._res_cb.setCurrentIndex(cur if cur >= 0 else 0)
        self._populate_hz(m["width"], m["height"], m.get("refreshRate", 60.0))

        self._scale_sb.setValue(m.get("scale", 1.0))
        self._rot_cb.setCurrentIndex(m.get("transform", 0))
        self._pos_x.setValue(m.get("x", 0))
        self._pos_y.setValue(m.get("y", 0))
        self._vrr_cb.setChecked(bool(m.get("vrr", False)))
        self._disabled_cb.setChecked(bool(m.get("disabled", False)))

        # Mirror dropdown — other monitors only
        self._mirror_cb.clear()
        self._mirror_cb.addItem("None", None)
        for other in (all_monitors or []):
            if other["name"] != m["name"]:
                self._mirror_cb.addItem(other["name"], other["name"])
        current_mirror = m.get("mirror")
        idx = self._mirror_cb.findData(current_mirror)
        self._mirror_cb.setCurrentIndex(idx if idx >= 0 else 0)

        # Disable resolution/position controls when mirroring
        mirroring = bool(current_mirror)
        self._set_mirror_mode(mirroring)

        self._busy = False
        self.setVisible(True)

    def _set_mirror_mode(self, mirroring):
        for w in (self._res_cb, self._hz_cb, self._pos_x, self._pos_y):
            w.setEnabled(not mirroring)

    def _populate_hz(self, width, height, current_hz=None):
        self._hz_cb.clear()
        for mode in self._modes:
            parsed = _parse_mode(mode)
            if parsed and parsed[0] == width and parsed[1] == height:
                self._hz_cb.addItem(f"{parsed[2]:.2f} Hz", parsed[2])
        if current_hz is not None:
            idx = self._hz_cb.findText(f"{current_hz:.2f} Hz")
            if idx >= 0:
                self._hz_cb.setCurrentIndex(idx)

    def _on_res(self, idx):
        if self._busy or not self._monitor or idx < 0:
            return
        data = self._res_cb.itemData(idx)
        if data:
            self._monitor["width"], self._monitor["height"] = data
            self._populate_hz(*data)

    def _on_hz(self, idx):
        if self._busy or not self._monitor or idx < 0:
            return
        hz = self._hz_cb.itemData(idx)
        if hz is not None:
            self._monitor["refreshRate"] = hz

    def _on_scale(self, val):
        if not self._busy and self._monitor:
            self._monitor["scale"] = val

    def _on_rot(self, idx):
        if not self._busy and self._monitor:
            self._monitor["transform"] = idx

    def _on_pos(self):
        if not self._busy and self._monitor:
            self._monitor["x"] = self._pos_x.value()
            self._monitor["y"] = self._pos_y.value()

    def _on_mirror(self, idx):
        if self._busy or not self._monitor:
            return
        target = self._mirror_cb.itemData(idx)
        self._monitor["mirror"] = target
        self._set_mirror_mode(bool(target))

    def _on_vrr(self, state):
        if not self._busy and self._monitor:
            self._monitor["vrr"] = bool(state)

    def _on_disabled(self, state):
        if not self._busy and self._monitor:
            self._monitor["disabled"] = bool(state)


# ── main tab ──────────────────────────────────────────────────────────────────

class DisplaysTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(QLabel("Displays"))
        header.addStretch()
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._apply)
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.clicked.connect(self._load)
        header.addWidget(self._apply_btn)
        header.addWidget(self._reload_btn)
        root.addLayout(header)

        self._status_lbl = QLabel("Loading…")
        root.addWidget(self._status_lbl)

        # Canvas + settings side by side
        body = QHBoxLayout()
        body.setSpacing(0)

        self._canvas = _MonitorCanvas()
        self._canvas.monitor_selected.connect(self._on_select)
        body.addWidget(self._canvas, stretch=3)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
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
        active = sum(1 for m in monitors if not m.get("disabled"))
        self._status_lbl.setText(
            f"{n} display(s) detected  ·  {active} active"
        )

    def _on_select(self, monitor):
        if monitor:
            self._settings.show_monitor(monitor, self._canvas._monitors)
        else:
            self._settings.setVisible(False)

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
