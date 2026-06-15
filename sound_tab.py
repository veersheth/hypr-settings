import json
import re
import subprocess
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip(), r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "", False


def _pw_dump():
    out, ok = _run(["pw-dump"])
    if not ok or not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _get_volume(node_id):
    """Returns (volume_pct: int, muted: bool) — (0, False) on failure."""
    out, ok = _run(["wpctl", "get-volume", str(node_id)])
    if not ok:
        return 0, False
    # "Volume: 0.80" or "Volume: 0.80 [MUTED]"
    m = re.match(r"Volume:\s*([\d.]+)", out)
    if not m:
        return 0, False
    return round(float(m.group(1)) * 100), "[MUTED]" in out


def _set_volume(node_id, pct, allow_boost=False):
    cmd = ["wpctl", "set-volume"]
    if allow_boost:
        cmd += ["-l", "1.5"]
    cmd += [str(node_id), f"{pct}%"]
    _run(cmd)


def _set_mute(node_id, muted):
    _run(["wpctl", "set-mute", str(node_id), "1" if muted else "0"])


def _parse_dump(dump):
    """Extract sinks, sources, streams, and active defaults from pw-dump."""
    sinks, sources, playback, record = [], [], [], []
    default_sink = ""
    default_source = ""

    for obj in dump:
        obj_type = obj.get("type", "")

        # Pull active defaults from metadata
        if "Metadata" in obj_type:
            if obj.get("props", {}).get("metadata.name") == "default":
                for entry in obj.get("metadata", []):
                    key = entry.get("key", "")
                    val = entry.get("value", {})
                    if key == "default.audio.sink" and isinstance(val, dict):
                        default_sink = val.get("name", "")
                    elif key == "default.audio.source" and isinstance(val, dict):
                        default_source = val.get("name", "")
            continue

        if "Node" not in obj_type:
            continue

        props = obj.get("info", {}).get("props", {})
        media_class = props.get("media.class", "")
        if not media_class:
            continue

        node_name = props.get("node.name", "")
        node = {
            "id": obj["id"],
            "name": node_name,
            "description": (
                props.get("node.description")
                or props.get("node.nick")
                or node_name
            ),
            "app_name": (
                props.get("application.name")
                or props.get("media.name")
                or props.get("node.description")
                or node_name
            ),
        }

        if media_class == "Audio/Sink":
            sinks.append(node)
        elif media_class == "Audio/Source" and ".monitor" not in node_name:
            sources.append(node)
        elif media_class == "Stream/Output/Audio":
            playback.append(node)
        elif media_class == "Stream/Input/Audio" and "Internal" not in media_class:
            record.append(node)

    return {
        "sinks": sinks,
        "sources": sources,
        "playback": playback,
        "record": record,
        "default_sink": default_sink,
        "default_source": default_source,
    }


# ── background loader ─────────────────────────────────────────────────────────

class _LoadThread(QThread):
    done = Signal(dict)
    error = Signal(str)

    def run(self):
        dump = _pw_dump()
        if dump is None:
            self.error.emit("pw-dump not available — is PipeWire running?")
            return
        data = _parse_dump(dump)
        for group in ("sinks", "sources", "playback", "record"):
            for node in data[group]:
                vol, muted = _get_volume(node["id"])
                node["volume"] = vol
                node["muted"] = muted
        self.done.emit(data)


# ── widgets ───────────────────────────────────────────────────────────────────

def _separator():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    return f


def _section_label(text):
    lbl = QLabel(text)
    lbl.setStyleSheet("font-weight: bold; font-size: 16px;")
    return lbl


def _fixed_label(text, width=70):
    lbl = QLabel(text)
    lbl.setFixedWidth(width)
    return lbl


class _AppStreamRow(QWidget):
    def __init__(self, node, allow_boost):
        super().__init__()
        self._node_id = node["id"]
        self._allow_boost = allow_boost
        self._busy = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        lbl = QLabel(node["app_name"])
        lbl.setFixedWidth(230)
        lbl.setToolTip(node["name"])
        layout.addWidget(lbl)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 150 if allow_boost else 100)
        self._slider.valueChanged.connect(self._on_volume)
        layout.addWidget(self._slider, stretch=1)

        self._pct_lbl = QLabel("0%")
        self._pct_lbl.setFixedWidth(50)
        layout.addWidget(self._pct_lbl)

        self._mute_cb = QCheckBox("Mute")
        self._mute_cb.stateChanged.connect(self._on_mute)
        layout.addWidget(self._mute_cb)

        self._busy = True
        self._slider.setValue(node.get("volume", 0))
        self._pct_lbl.setText(f"{node.get('volume', 0)}%")
        self._mute_cb.setChecked(node.get("muted", False))
        self._busy = False

    def _on_volume(self, val):
        self._pct_lbl.setText(f"{val}%")
        if not self._busy:
            _set_volume(self._node_id, val, self._allow_boost)

    def _on_mute(self, state):
        if not self._busy:
            _set_mute(self._node_id, state == Qt.Checked)


# ── main tab ──────────────────────────────────────────────────────────────────

class SoundTab(QWidget):
    def __init__(self):
        super().__init__()
        self._data = {}
        self._load_thread = None
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("Sound"))
        header.addStretch()
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.clicked.connect(self._load)
        header.addWidget(self._reload_btn)
        root.addLayout(header)

        self._status_lbl = QLabel("Loading…")
        root.addWidget(self._status_lbl)
        root.addWidget(_separator())

        # ── Output ───────────────────────────────────────────────────────────
        root.addWidget(_section_label("Output"))

        out_dev = QHBoxLayout()
        out_dev.addWidget(_fixed_label("Device"))
        self._sink_combo = QComboBox()
        self._sink_combo.setMinimumWidth(320)
        self._sink_combo.currentIndexChanged.connect(self._on_sink_change)
        out_dev.addWidget(self._sink_combo, stretch=1)
        root.addLayout(out_dev)

        out_vol = QHBoxLayout()
        out_vol.addWidget(_fixed_label("Volume"))
        self._sink_slider = QSlider(Qt.Horizontal)
        self._sink_slider.setRange(0, 150)
        self._sink_slider.valueChanged.connect(self._on_sink_volume)
        out_vol.addWidget(self._sink_slider, stretch=1)
        self._sink_vol_lbl = QLabel("0%")
        self._sink_vol_lbl.setFixedWidth(50)
        out_vol.addWidget(self._sink_vol_lbl)
        self._sink_mute_cb = QCheckBox("Mute")
        self._sink_mute_cb.stateChanged.connect(self._on_sink_mute)
        out_vol.addWidget(self._sink_mute_cb)
        root.addLayout(out_vol)

        root.addWidget(_separator())

        # ── Input ────────────────────────────────────────────────────────────
        root.addWidget(_section_label("Input"))

        in_dev = QHBoxLayout()
        in_dev.addWidget(_fixed_label("Device"))
        self._source_combo = QComboBox()
        self._source_combo.setMinimumWidth(320)
        self._source_combo.currentIndexChanged.connect(self._on_source_change)
        in_dev.addWidget(self._source_combo, stretch=1)
        root.addLayout(in_dev)

        in_vol = QHBoxLayout()
        in_vol.addWidget(_fixed_label("Volume"))
        self._source_slider = QSlider(Qt.Horizontal)
        self._source_slider.setRange(0, 100)
        self._source_slider.valueChanged.connect(self._on_source_volume)
        in_vol.addWidget(self._source_slider, stretch=1)
        self._source_vol_lbl = QLabel("0%")
        self._source_vol_lbl.setFixedWidth(50)
        in_vol.addWidget(self._source_vol_lbl)
        self._source_mute_cb = QCheckBox("Mute")
        self._source_mute_cb.stateChanged.connect(self._on_source_mute)
        in_vol.addWidget(self._source_mute_cb)
        root.addLayout(in_vol)

        root.addWidget(_separator())

        # ── Applications ──────────────────────────────────────────────────────
        root.addWidget(_section_label("Applications"))
        self._apps_status = QLabel("No active streams")
        root.addWidget(self._apps_status)

        self._apps_widget = QWidget()
        self._apps_layout = QVBoxLayout(self._apps_widget)
        self._apps_layout.setContentsMargins(0, 0, 0, 0)
        self._apps_layout.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidget(self._apps_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMaximumHeight(240)
        root.addWidget(scroll)

        root.addStretch()

    # ── loading ───────────────────────────────────────────────────────────────

    def _load(self):
        if self._load_thread and self._load_thread.isRunning():
            return
        self._reload_btn.setEnabled(False)
        self._status_lbl.setText("Loading…")
        self._load_thread = _LoadThread()
        self._load_thread.done.connect(self._on_loaded)
        self._load_thread.error.connect(self._on_error)
        self._load_thread.start()

    def _on_error(self, msg):
        self._reload_btn.setEnabled(True)
        self._status_lbl.setText(f"Error: {msg}")

    def _on_loaded(self, data):
        self._data = data
        self._reload_btn.setEnabled(True)

        sinks = data["sinks"]
        sources = data["sources"]
        default_sink = data["default_sink"]
        default_source = data["default_source"]

        # Sinks
        self._sink_combo.blockSignals(True)
        self._sink_combo.clear()
        for i, sink in enumerate(sinks):
            self._sink_combo.addItem(sink["description"], sink["name"])
            if sink["name"] == default_sink:
                self._sink_combo.setCurrentIndex(i)
        self._sink_combo.blockSignals(False)
        self._refresh_sink_controls()

        # Sources
        self._source_combo.blockSignals(True)
        self._source_combo.clear()
        for i, src in enumerate(sources):
            self._source_combo.addItem(src["description"], src["name"])
            if src["name"] == default_source:
                self._source_combo.setCurrentIndex(i)
        self._source_combo.blockSignals(False)
        self._refresh_source_controls()

        self._populate_apps(data["playback"], data["record"])

        self._status_lbl.setText(
            f"{len(sinks)} output(s)  ·  {len(sources)} input(s)"
        )

    # ── sink controls ─────────────────────────────────────────────────────────

    def _refresh_sink_controls(self):
        idx = self._sink_combo.currentIndex()
        sinks = self._data.get("sinks", [])
        if not (0 <= idx < len(sinks)):
            return
        node = sinks[idx]
        self._sink_slider.blockSignals(True)
        self._sink_mute_cb.blockSignals(True)
        self._sink_slider.setValue(node.get("volume", 0))
        self._sink_vol_lbl.setText(f"{node.get('volume', 0)}%")
        self._sink_mute_cb.setChecked(node.get("muted", False))
        self._sink_slider.blockSignals(False)
        self._sink_mute_cb.blockSignals(False)

    def _on_sink_change(self, idx):
        sinks = self._data.get("sinks", [])
        if 0 <= idx < len(sinks):
            _run(["wpctl", "set-default", str(sinks[idx]["id"])])
            self._refresh_sink_controls()

    def _on_sink_volume(self, val):
        self._sink_vol_lbl.setText(f"{val}%")
        idx = self._sink_combo.currentIndex()
        sinks = self._data.get("sinks", [])
        if 0 <= idx < len(sinks):
            _set_volume(sinks[idx]["id"], val, allow_boost=True)

    def _on_sink_mute(self, state):
        idx = self._sink_combo.currentIndex()
        sinks = self._data.get("sinks", [])
        if 0 <= idx < len(sinks):
            _set_mute(sinks[idx]["id"], state == Qt.Checked)

    # ── source controls ───────────────────────────────────────────────────────

    def _refresh_source_controls(self):
        idx = self._source_combo.currentIndex()
        sources = self._data.get("sources", [])
        if not (0 <= idx < len(sources)):
            return
        node = sources[idx]
        self._source_slider.blockSignals(True)
        self._source_mute_cb.blockSignals(True)
        self._source_slider.setValue(min(node.get("volume", 0), 100))
        self._source_vol_lbl.setText(f"{node.get('volume', 0)}%")
        self._source_mute_cb.setChecked(node.get("muted", False))
        self._source_slider.blockSignals(False)
        self._source_mute_cb.blockSignals(False)

    def _on_source_change(self, idx):
        sources = self._data.get("sources", [])
        if 0 <= idx < len(sources):
            _run(["wpctl", "set-default", str(sources[idx]["id"])])
            self._refresh_source_controls()

    def _on_source_volume(self, val):
        self._source_vol_lbl.setText(f"{val}%")
        idx = self._source_combo.currentIndex()
        sources = self._data.get("sources", [])
        if 0 <= idx < len(sources):
            _set_volume(sources[idx]["id"], val, allow_boost=False)

    def _on_source_mute(self, state):
        idx = self._source_combo.currentIndex()
        sources = self._data.get("sources", [])
        if 0 <= idx < len(sources):
            _set_mute(sources[idx]["id"], state == Qt.Checked)

    # ── application streams ───────────────────────────────────────────────────

    def _populate_apps(self, playback, record):
        while self._apps_layout.count():
            item = self._apps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        streams = [(n, True) for n in playback] + [(n, False) for n in record]
        if not streams:
            self._apps_status.setText("No active streams")
            return

        self._apps_status.setText(f"{len(streams)} active stream(s)")
        for node, is_playback in streams:
            self._apps_layout.addWidget(_AppStreamRow(node, allow_boost=is_playback))
        self._apps_layout.addStretch()
