import os
import platform
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)
from common import run, separator, make_centered


def _load_info():
    info = {}

    info["hostname"] = platform.node()

    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    info["os"] = line.split("=", 1)[1].strip().strip('"')
                    break
    except OSError:
        info["os"] = platform.system()

    info["kernel"] = platform.release()

    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        mins = rem // 60
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{mins}m")
        info["uptime"] = " ".join(parts)
    except OSError:
        info["uptime"] = "—"

    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
            else:
                info["cpu"] = platform.processor() or "—"
    except OSError:
        info["cpu"] = "—"
    info["cores"] = str(os.cpu_count() or "—")

    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                mem[k.strip()] = int(v.split()[0])
        total_mb = mem["MemTotal"] // 1024
        used_mb = (mem["MemTotal"] - mem["MemAvailable"]) // 1024
        info["ram"] = f"{used_mb} / {total_mb} MB"
    except (OSError, KeyError):
        info["ram"] = "—"

    out, ok = run(["lspci"])
    if ok:
        gpus = [
            line.split(":", 2)[-1].strip()
            for line in out.splitlines()
            if any(x in line for x in ("VGA compatible", "3D controller", "Display controller"))
        ]
        info["gpu"] = gpus[0] if gpus else "—"
    else:
        info["gpu"] = "—"

    return info


class _LoadThread(QThread):
    done = Signal(dict)

    def run(self):
        self.done.emit(_load_info())


def _section_label(text):
    lbl = QLabel(text)
    lbl.setObjectName("sectionTitle")
    return lbl


class SystemTab(QWidget):
    def __init__(self):
        super().__init__()
        self._load_thread = None
        self._vals = {}
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(make_centered(self))
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("System")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.clicked.connect(self._load)
        header.addWidget(self._reload_btn)
        root.addLayout(header)

        self._status_lbl = QLabel("Loading…")
        self._status_lbl.setObjectName("statusLabel")
        root.addWidget(self._status_lbl)

        root.addWidget(separator())
        root.addWidget(_section_label("System"))
        root.addLayout(self._section([
            ("hostname", "Hostname"),
            ("os",       "OS"),
            ("kernel",   "Kernel"),
            ("uptime",   "Uptime"),
        ]))

        root.addWidget(separator())
        root.addWidget(_section_label("Hardware"))
        root.addLayout(self._section([
            ("cpu",   "CPU"),
            ("cores", "Cores"),
            ("ram",   "Memory"),
            ("gpu",   "GPU"),
        ]))


        root.addStretch()

    def _section(self, fields):
        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setColumnMinimumWidth(0, 100)
        for i, (key, label) in enumerate(fields):
            lbl = QLabel(label)
            lbl.setObjectName("fieldLabel")
            lbl.setAlignment(Qt.AlignTop)
            val = QLabel("—")
            val.setWordWrap(True)
            grid.addWidget(lbl, i, 0)
            grid.addWidget(val, i, 1)
            self._vals[key] = val
        return grid

    def _load(self):
        if self._load_thread and self._load_thread.isRunning():
            return
        self._reload_btn.setEnabled(False)
        self._status_lbl.setText("Loading…")
        self._load_thread = _LoadThread()
        self._load_thread.done.connect(self._on_done)
        self._load_thread.start()

    def _on_done(self, info):
        for key, lbl in self._vals.items():
            lbl.setText(info.get(key, "—"))
        self._reload_btn.setEnabled(True)
        self._status_lbl.setText("")
