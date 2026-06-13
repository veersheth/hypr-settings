import subprocess
import threading
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QScrollArea, QFrame
from PySide6.QtCore import Qt, QThread, Signal


class _ScanThread(QThread):
    done = Signal(list)
    error = Signal(str)

    def run(self):
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,ACTIVE",
                 "device", "wifi", "list", "--rescan", "auto"],
                capture_output=True, text=True, timeout=15
            )
            networks, seen = [], set()
            for line in result.stdout.splitlines():
                parts = line.split(":")
                if len(parts) < 4:
                    continue
                ssid, signal_str, security, active = parts[0], parts[1], parts[2], parts[3]
                if not ssid or ssid in seen:
                    continue
                seen.add(ssid)
                try:
                    signal = int(signal_str)
                except ValueError:
                    signal = 0
                networks.append({
                    "ssid": ssid,
                    "signal": signal,
                    "security": security or "Open",
                    "connected": active.strip().lower() == "yes",
                })
            networks.sort(key=lambda n: (-n["connected"], -n["signal"]))
            self.done.emit(networks)
        except FileNotFoundError:
            self.error.emit("nmcli not found")
        except subprocess.TimeoutExpired:
            self.error.emit("Scan timed out")


class WifiTab(QWidget):
    def __init__(self):
        super().__init__()
        self._thread = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(QLabel("Nearby Networks"))
        header.addStretch()
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.clicked.connect(self._scan)
        header.addWidget(self._reload_btn)
        root.addLayout(header)

        self._status = QLabel("Scanning…")
        root.addWidget(self._status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()

        scroll.setWidget(self._list)
        root.addWidget(scroll, stretch=1)

        self._scan()

    def _scan(self):
        if self._thread and self._thread.isRunning():
            return
        self._reload_btn.setEnabled(False)
        self._status.setText("Scanning…")
        self._clear()
        self._thread = _ScanThread()
        self._thread.done.connect(self._on_done)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _clear(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_done(self, networks):
        self._reload_btn.setEnabled(True)
        if not networks:
            self._status.setText("No networks found")
            return
        self._status.setText(f"{len(networks)} network(s) found")
        for i, net in enumerate(networks):
            text = net["ssid"]
            if net["connected"]:
                text += "  Connected"
            self._list_layout.insertWidget(i, QLabel(text))

    def _on_error(self, msg):
        self._reload_btn.setEnabled(True)
        self._status.setText(f"Error: {msg}")
