import json
import os
import re
from PySide6.QtCore import Qt, QRect, QPoint, QThread, Signal
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)
from common import run, separator, make_centered
import signal
import tempfile
from monitor_profiles import (
    profile_key   as _profile_key,
    display_id    as _display_id,
    load_profiles as _load_profiles,
    save_profile  as _save_profile,
    delete_profile as _delete_profile,
    write_monitors_lua,
    MONITORS_LUA,
    daemon_pid    as _daemon_pid,
)

TRANSFORMS = [
    ("Normal", 0), ("90°", 1), ("180°", 2), ("270°", 3),
    ("Flipped", 4), ("Flipped + 90°", 5), ("Flipped + 180°", 6), ("Flipped + 270°", 7),
]

COLORS = ["#2a5298", "#7b2d8b", "#1e7a4a", "#8b4513", "#1a6b8a", "#6b1a3a"]


def _parse_mode(s):
    s = s.replace("Hz", "")
    res, _, rr = s.partition("@")
    w, _, h = res.partition("x")
    return int(w), int(h), float(rr or "0")


def _format_mode(w, h, rr):
    return f"{w}×{h} @ {rr:.0f} Hz"


def _load_monitors():
    out, ok = run(["hyprctl", "monitors", "all", "-j"])
    if not ok or not out:
        return None, "hyprctl not available — are you running Hyprland?"
    try:
        monitors = json.loads(out)
    except json.JSONDecodeError:
        return None, "Failed to parse hyprctl output"
    for m in monitors:
        raw = m.get("mirrorOf", "none")
        m["mirror"] = None if raw == "none" else raw
        m.setdefault("_workspaces", [])
    return monitors, None


def _logical_size(m):
    s = m.get("scale", 1.0) or 1.0
    t = m.get("transform", 0)
    w, h = int(m["width"] / s), int(m["height"] / s)
    return (h, w) if t in (1, 3, 5, 7) else (w, h)


def _preset_mirror(monitors):
    if len(monitors) < 2:
        return monitors, None
    primary = next((m for m in monitors if m.get("focused")), monitors[0])
    result = []
    for m in monitors:
        mc = dict(m)
        mc["mirror"] = None if mc["name"] == primary["name"] else primary["name"]
        mc["_workspaces"] = []
        result.append(mc)
    return result, primary["name"]


def _preset_extend(monitors):
    sorted_mons = sorted(monitors, key=lambda m: (m.get("x", 0), m.get("y", 0)))
    result = []
    x_offset = 0
    for m in sorted_mons:
        mc = dict(m)
        mc["mirror"] = None
        mc["x"] = x_offset
        mc["y"] = 0
        lw, _ = _logical_size(mc)
        x_offset += lw
        result.append(mc)
    return result


class _ReloadThread(QThread):
    done = Signal(bool)

    def __init__(self, dispatch_cmds=None):
        super().__init__()
        self._dispatch_cmds = dispatch_cmds or []

    def run(self):
        _, ok = run(["hyprctl", "reload"])
        if ok:
            for cmd in self._dispatch_cmds:
                run(["hyprctl", "dispatch", cmd])
        self.done.emit(ok)


# ── Canvas ──────────────────────────────────────────────────────────────────

class _MonitorCanvas(QWidget):
    monitor_selected = Signal(object)
    position_changed = Signal(int, int)

    PAD = 32

    def __init__(self):
        super().__init__()
        self._monitors = []
        self._sel = -1
        self._drag = -1
        self._drag_screen_off = QPoint()
        self._drag_min_x = 0
        self._drag_min_y = 0
        self._drag_scale = 0.1
        self._scale = 0.1
        self._min_x = 0
        self._min_y = 0
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_monitors(self, monitors):
        self._monitors = monitors
        self._sel = -1
        self._drag = -1
        self._recompute()
        self.update()

    def _recompute(self):
        if not self._monitors:
            return
        lws = [_logical_size(m)[0] for m in self._monitors]
        lhs = [_logical_size(m)[1] for m in self._monitors]
        self._min_x = min(m["x"] for m in self._monitors)
        self._min_y = min(m["y"] for m in self._monitors)
        total_w = max(m["x"] + w for m, w in zip(self._monitors, lws)) - self._min_x
        total_h = max(m["y"] + h for m, h in zip(self._monitors, lhs)) - self._min_y
        avail_w = max(self.width() - 2 * self.PAD, 1)
        avail_h = max(self.height() - 2 * self.PAD, 1)
        if total_w > 0 and total_h > 0:
            self._scale = min(avail_w / total_w, avail_h / total_h)

    def _rect(self, m, min_x=None, min_y=None, scale=None):
        lw, lh = _logical_size(m)
        mx = self._min_x if min_x is None else min_x
        my = self._min_y if min_y is None else min_y
        sc = self._scale if scale is None else scale
        x = int((m["x"] - mx) * sc) + self.PAD
        y = int((m["y"] - my) * sc) + self.PAD
        return QRect(x, y, max(int(lw * sc), 20), max(int(lh * sc), 20))

    def _snap(self, idx):
        if len(self._monitors) > 1:
            self._force_touch(idx)

    def _force_touch(self, idx):
        m = self._monitors[idx]
        lw, lh = _logical_size(m)
        best_d = float("inf")
        best_dx = best_dy = 0
        for i, other in enumerate(self._monitors):
            if i == idx:
                continue
            ow, oh = _logical_size(other)
            ox, oy = other["x"], other["y"]
            for sdx, sdy in [
                ((m["x"] + lw) - ox,  0),
                (m["x"] - (ox + ow),  0),
                (0, (m["y"] + lh) - oy),
                (0,  m["y"] - (oy + oh)),
            ]:
                d = abs(sdx) + abs(sdy)
                if d < best_d:
                    best_d = d
                    best_dx, best_dy = sdx, sdy
        m["x"] -= int(best_dx)
        m["y"] -= int(best_dy)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#141414"))

        font = p.font()
        font.setPixelSize(12)
        p.setFont(font)

        min_x = self._drag_min_x if self._drag >= 0 else self._min_x
        min_y = self._drag_min_y if self._drag >= 0 else self._min_y
        scale = self._drag_scale if self._drag >= 0 else self._scale

        for i, m in enumerate(self._monitors):
            rect = self._rect(m, min_x, min_y, scale)
            color = QColor(COLORS[i % len(COLORS)])
            selected = (i == self._sel)
            p.fillRect(rect, color.lighter(145) if selected else color)
            if selected:
                p.setPen(QPen(QColor("#ffffff"), 2))
                p.drawRect(rect.adjusted(1, 1, -1, -1))
            lw, lh = _logical_size(m)
            label = m["name"] + "\n" + str(lw) + "×" + str(lh)
            if m.get("mirror"):
                label += "\n→ " + m["mirror"]
            p.setPen(QColor("#ffffff"))
            p.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, label)

        p.end()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        for i in range(len(self._monitors) - 1, -1, -1):
            r = self._rect(self._monitors[i])
            if r.contains(e.pos()):
                self._sel = i
                self._drag = i
                self._drag_screen_off = e.pos() - r.topLeft()
                self._drag_min_x = self._min_x
                self._drag_min_y = self._min_y
                self._drag_scale = self._scale
                self.monitor_selected.emit(self._monitors[i])
                self.update()
                return
        self._sel = -1
        self.monitor_selected.emit(None)
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag < 0:
            return
        m = self._monitors[self._drag]
        top_left = e.pos() - self._drag_screen_off
        m["x"] = int((top_left.x() - self.PAD) / self._drag_scale) + self._drag_min_x
        m["y"] = int((top_left.y() - self.PAD) / self._drag_scale) + self._drag_min_y
        self.position_changed.emit(m["x"], m["y"])
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag >= 0:
            self._snap(self._drag)
            m = self._monitors[self._drag]
            self._drag = -1
            self._recompute()
            self.position_changed.emit(m["x"], m["y"])
            self.update()

    def resizeEvent(self, _):
        if self._drag < 0:
            self._recompute()
        self.update()


# ── Settings panel ──────────────────────────────────────────────────────────

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

        self._mode_combo = QComboBox()
        self._mode_combo.currentIndexChanged.connect(self._on_mode)
        row("Resolution", self._mode_combo)

        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(0.25, 4.0)
        self._scale_spin.setSingleStep(0.25)
        self._scale_spin.setDecimals(2)
        self._scale_spin.valueChanged.connect(self._on_scale)
        row("Scale", self._scale_spin)

        self._transform_combo = QComboBox()
        for label, val in TRANSFORMS:
            self._transform_combo.addItem(label, val)
        self._transform_combo.currentIndexChanged.connect(self._on_transform)
        row("Rotation", self._transform_combo)

        root.addWidget(separator())

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

        root.addWidget(separator())

        self._ws_edit = QLineEdit()
        self._ws_edit.setPlaceholderText("e.g. 1, 2, 3 or 1-5")
        self._ws_edit.textChanged.connect(self._on_workspaces)
        row("Workspaces", self._ws_edit)

        root.addStretch()
        self.setVisible(False)

    def show_monitor(self, m, all_monitors=None):
        self._monitor = m
        self._busy = True

        self._name_lbl.setText(m["name"])
        desc = m.get("description", "")
        self._desc_lbl.setText(desc)
        self._desc_lbl.setVisible(bool(desc))

        self._mode_combo.clear()
        modes = m.get("availableModes", [])
        sel_idx = 0
        for i, mode_str in enumerate(modes):
            w, h, rr = _parse_mode(mode_str)
            self._mode_combo.addItem(_format_mode(w, h, rr), (w, h, rr))
            if w == m["width"] and h == m["height"] and abs(rr - m["refreshRate"]) < 0.5:
                sel_idx = i
        if not modes:
            self._mode_combo.addItem(
                _format_mode(m["width"], m["height"], m["refreshRate"]),
                (m["width"], m["height"], m["refreshRate"]),
            )
        self._mode_combo.setCurrentIndex(sel_idx)

        self._scale_spin.setValue(m.get("scale", 1.0))

        idx = self._transform_combo.findData(m.get("transform", 0))
        self._transform_combo.setCurrentIndex(idx if idx >= 0 else 0)

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

        ws_ids = m.get("_workspaces", [])
        self._ws_edit.setText(", ".join(str(w) for w in ws_ids))

        self._busy = False
        self.setVisible(True)

    def update_position(self, x, y):
        self._busy = True
        self._pos_x.setValue(x)
        self._pos_y.setValue(y)
        self._busy = False

    def _set_position_enabled(self, enabled):
        self._pos_x.setEnabled(enabled)
        self._pos_y.setEnabled(enabled)

    def _on_mode(self, _):
        if self._busy or not self._monitor:
            return
        data = self._mode_combo.currentData()
        if data:
            self._monitor["width"], self._monitor["height"], self._monitor["refreshRate"] = data

    def _on_scale(self, val):
        if not self._busy and self._monitor:
            self._monitor["scale"] = val

    def _on_transform(self, _):
        if not self._busy and self._monitor:
            self._monitor["transform"] = self._transform_combo.currentData()

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

    def _on_workspaces(self, text):
        if not self._busy and self._monitor:
            self._monitor["_workspaces"] = _parse_workspace_input(text)


def _parse_workspace_input(text):
    ids = []
    for part in re.split(r"[,\s]+", text.strip()):
        part = part.strip()
        if not part:
            continue
        hit = re.match(r"^(\d+)-(\d+)$", part)
        if hit:
            a, b = int(hit.group(1)), int(hit.group(2))
            ids.extend(range(min(a, b), max(a, b) + 1))
        elif part.isdigit():
            ids.append(int(part))
    return sorted(set(ids))


# ── Main tab ────────────────────────────────────────────────────────────────

class DisplaysTab(QWidget):
    def __init__(self):
        super().__init__()
        self._monitors = []
        self._reload_thread = None
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(make_centered(self))
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        # ── Header ──
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Displays")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self._edid_cb = QCheckBox("Match by display ID")
        self._edid_cb.setToolTip(
            "Use display description (EDID) instead of port name.\n"
            "Arrangement survives plugging into a different port."
        )
        header.addWidget(self._edid_cb)
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

        # ── Profile banner ──
        self._profile_bar = QWidget()
        pb = QHBoxLayout(self._profile_bar)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(8)
        self._profile_lbl = QLabel()
        self._profile_lbl.setObjectName("statusLabel")
        pb.addWidget(self._profile_lbl, stretch=1)
        self._restore_btn = QPushButton("Restore saved profile")
        self._restore_btn.clicked.connect(self._restore_profile)
        pb.addWidget(self._restore_btn)
        self._delete_profile_btn = QPushButton("Delete profile")
        self._delete_profile_btn.clicked.connect(self._delete_current_profile)
        pb.addWidget(self._delete_profile_btn)
        self._profile_bar.setVisible(False)
        root.addWidget(self._profile_bar)

        # ── Presets ──
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        self._mirror_btn = QPushButton("Mirror All")
        self._mirror_btn.clicked.connect(self._on_mirror_preset)
        self._extend_btn = QPushButton("Extend")
        self._extend_btn.clicked.connect(self._on_extend_preset)
        preset_row.addWidget(self._mirror_btn)
        preset_row.addWidget(self._extend_btn)
        preset_row.addStretch()
        root.addLayout(preset_row)

        # ── Canvas + settings ──
        body = QHBoxLayout()
        body.setSpacing(0)

        canvas_wrap = QVBoxLayout()
        canvas_wrap.setContentsMargins(0, 0, 16, 0)
        self._canvas = _MonitorCanvas()
        self._canvas.monitor_selected.connect(self._on_select)
        self._canvas.position_changed.connect(self._on_position_changed)
        canvas_wrap.addWidget(self._canvas)
        body.addLayout(canvas_wrap, stretch=3)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        body.addWidget(sep)

        self._settings = _SettingsPanel()
        body.addWidget(self._settings, stretch=2)

        root.addLayout(body, stretch=1)

        # ── Daemon status ──
        root.addWidget(separator())
        daemon_row = QHBoxLayout()
        self._daemon_lbl = QLabel()
        self._daemon_lbl.setObjectName("statusLabel")
        daemon_row.addWidget(self._daemon_lbl, stretch=1)
        self._daemon_btn = QPushButton()
        self._daemon_btn.setFixedWidth(80)
        self._daemon_btn.clicked.connect(self._toggle_daemon)
        daemon_row.addWidget(self._daemon_btn)
        root.addLayout(daemon_row)
        self._refresh_daemon_status()

    # ── Loading ──────────────────────────────────────────────────────────────

    def _load(self):
        monitors, err = _load_monitors()
        if err:
            self._status_lbl.setText(f"Error: {err}")
            self._profile_bar.setVisible(False)
            return
        self._monitors = monitors

        # hyprctl doesn't know about _workspaces — restore from saved profile
        key = _profile_key(self._monitors)
        profiles = _load_profiles()
        if key in profiles:
            saved_by_id = {_display_id(m): m for m in profiles[key]["monitors"]}
            for m in self._monitors:
                saved = saved_by_id.get(_display_id(m))
                if saved:
                    m["_workspaces"] = saved.get("_workspaces", [])

        self._canvas.set_monitors(self._monitors)
        self._settings.setVisible(False)
        self._update_profile_bar()

    def _update_profile_bar(self):
        n = len(self._monitors)
        if not self._monitors:
            self._status_lbl.setText("No displays detected")
            self._profile_bar.setVisible(False)
            return

        key = _profile_key(self._monitors)
        profiles = _load_profiles()
        saved = key in profiles

        self._status_lbl.setText(
            f"{n} display(s) — drag to reposition, click to configure"
        )
        self._profile_lbl.setText(
            f"Profile: {key}   {'[saved]' if saved else '[not yet saved — click Apply]'}"
        )
        self._restore_btn.setVisible(saved)
        self._delete_profile_btn.setVisible(saved)
        self._profile_bar.setVisible(True)

    # ── Apply / save ─────────────────────────────────────────────────────────

    def _apply(self):
        if not self._monitors:
            return
        use_edid = self._edid_cb.isChecked()
        try:
            write_monitors_lua(self._monitors, use_edid=use_edid)
        except OSError as e:
            self._status_lbl.setText(f"Save failed: {e}")
            return

        # Save profile for the current monitor combination
        key = _profile_key(self._monitors)
        _save_profile(key, self._monitors, use_edid)

        self._set_busy(True)
        self._status_lbl.setText("Reloading Hyprland config…")
        dispatch_cmds = []
        for m in self._monitors:
            for ws_id in m.get("_workspaces", []):
                dispatch_cmds.append(
                    "hl.dsp.workspace.move({ monitor = '" + m["name"] + "', workspace = " + str(ws_id) + " })"
                )
        self._reload_thread = _ReloadThread(dispatch_cmds)
        self._reload_thread.done.connect(self._on_reload_done)
        self._reload_thread.start()

    def _on_reload_done(self, ok):
        self._set_busy(False)
        key = _profile_key(self._monitors)
        if ok:
            self._status_lbl.setText(f"Applied — profile saved for: {key}")
        else:
            self._status_lbl.setText(f"Profile saved for: {key} — Hyprland reload failed, restart to apply")
        self._update_profile_bar()

    # ── Profile restore / delete ─────────────────────────────────────────────

    def _restore_profile(self):
        """Load saved profile settings into the UI without applying."""
        key = _profile_key(self._monitors)
        profiles = _load_profiles()
        if key not in profiles:
            return

        saved = profiles[key]["monitors"]
        use_edid = profiles[key].get("use_edid", False)
        self._edid_cb.setChecked(use_edid)

        # Map saved configs onto live monitors by display_id so availableModes
        # and current port names are preserved from hyprctl.
        saved_by_id = {_display_id(m): m for m in saved}
        for m in self._monitors:
            saved_m = saved_by_id.get(_display_id(m))
            if not saved_m:
                continue
            m["width"]       = saved_m["width"]
            m["height"]      = saved_m["height"]
            m["refreshRate"] = saved_m["refreshRate"]
            m["x"]           = saved_m["x"]
            m["y"]           = saved_m["y"]
            m["scale"]       = saved_m["scale"]
            m["transform"]   = saved_m.get("transform", 0)
            m["mirror"]      = saved_m.get("mirror")
            m["disabled"]    = saved_m.get("disabled", False)
            m["_workspaces"] = saved_m.get("_workspaces", [])

        self._canvas.set_monitors(self._monitors)
        self._settings.setVisible(False)
        self._status_lbl.setText(f"Restored profile for: {key} — click Apply to activate")

    def _delete_current_profile(self):
        key = _profile_key(self._monitors)
        _delete_profile(key)
        self._update_profile_bar()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _on_select(self, monitor):
        if monitor:
            self._settings.show_monitor(monitor, self._monitors)
        else:
            self._settings.setVisible(False)

    def _on_position_changed(self, x, y):
        self._settings.update_position(x, y)

    def _set_busy(self, busy):
        self._apply_btn.setEnabled(not busy)
        self._reload_btn.setEnabled(not busy)
        self._mirror_btn.setEnabled(not busy)
        self._extend_btn.setEnabled(not busy)
        self._edid_cb.setEnabled(not busy)
        self._restore_btn.setEnabled(not busy)
        self._delete_profile_btn.setEnabled(not busy)

    def _on_mirror_preset(self):
        if not self._monitors:
            return
        if len(self._monitors) < 2:
            self._status_lbl.setText("Only one display connected — connect another to mirror")
            return
        result, primary_name = _preset_mirror(self._monitors)
        self._monitors = result
        self._canvas.set_monitors(self._monitors)
        self._settings.setVisible(False)
        self._status_lbl.setText(f"Set to mirror {primary_name} — click Apply to save")

    def _on_extend_preset(self):
        if not self._monitors:
            return
        result = _preset_extend(self._monitors)
        self._monitors = result
        self._canvas.set_monitors(self._monitors)
        self._settings.setVisible(False)
        names = " + ".join(m["name"] for m in result)
        self._status_lbl.setText(f"Extending: {names} — click Apply to save")

    # ── Daemon controls ──────────────────────────────────────────────────────

    def _refresh_daemon_status(self):
        pid = _daemon_pid()
        if pid:
            self._daemon_lbl.setText(f"Monitor daemon: running (PID {pid})")
            self._daemon_btn.setText("Stop")
        else:
            self._daemon_lbl.setText("Monitor daemon: not running")
            self._daemon_btn.setText("Start")

    def _toggle_daemon(self):
        pid = _daemon_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        else:
            _daemon_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "monitor_daemon.py"
            )
            if os.path.exists(_daemon_path):
                import subprocess as _sp, sys as _sys
                _sp.Popen([_sys.executable, _daemon_path])
        # Give the process a moment to start/die before refreshing
        from PySide6.QtCore import QTimer
        QTimer.singleShot(400, self._refresh_daemon_status)
