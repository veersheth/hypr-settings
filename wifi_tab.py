import re
import subprocess
import threading
from PySide6.QtCore import Qt, QMetaObject, QThread, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)


def _run(cmd):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.stdout.strip(), result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "", False


def _wifi_device():
    out, _ = _run(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "wifi":
            return parts[0]
    return None


def _saved_connection(ssid):
    out, _ = _run(["nmcli", "-t", "-f", "NAME", "connection", "show"])
    return ssid in out.splitlines()


def _parse_nmcli_line(line):
    # nmcli terse mode escapes ':' in values as '\:' — split on unescaped ':' only
    parts = re.split(r'(?<!\\):', line, maxsplit=3)
    if len(parts) < 4:
        return None
    ssid, signal_str, security, active = parts
    ssid = ssid.replace("\\:", ":")
    if not ssid:
        return None
    try:
        signal = int(signal_str)
    except ValueError:
        signal = 0
    return {
        "ssid": ssid,
        "signal": signal,
        "security": security or "Open",
        "connected": active.strip().lower() == "yes",
    }


class _ScanThread(QThread):
    done = Signal(list)
    error = Signal(str)

    def run(self):
        out, ok = _run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,ACTIVE",
                         "device", "wifi", "list", "--rescan", "auto"])
        if not ok and not out:
            self.error.emit("nmcli unavailable")
            return
        networks, seen = [], set()
        for line in out.splitlines():
            net = _parse_nmcli_line(line)
            if net and net["ssid"] not in seen:
                seen.add(net["ssid"])
                networks.append(net)
        networks.sort(key=lambda n: (-n["connected"], -n["signal"]))
        self.done.emit(networks)


class _DetailPanel(QWidget):
    connect_requested = Signal(dict)
    forget_requested = Signal(dict)

    def __init__(self):
        super().__init__()
        self._network = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 0, 0, 0)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignTop)

        self._ssid_lbl = QLabel()
        self._ssid_lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(self._ssid_lbl)

        self._signal_lbl = QLabel()
        self._security_lbl = QLabel()
        self._status_lbl = QLabel()
        for lbl in (self._signal_lbl, self._security_lbl, self._status_lbl):
            layout.addWidget(lbl)

        layout.addSpacing(8)

        self._connect_btn = QPushButton()
        self._connect_btn.clicked.connect(lambda: self.connect_requested.emit(self._network))
        layout.addWidget(self._connect_btn)

        self._forget_btn = QPushButton("Forget Network")
        self._forget_btn.clicked.connect(lambda: self.forget_requested.emit(self._network))
        layout.addWidget(self._forget_btn)

        layout.addStretch()
        self.setVisible(False)

    def show_network(self, network: dict):
        self._network = network
        self._ssid_lbl.setText(network["ssid"])
        self._signal_lbl.setText(f"Signal: {network['signal']}%")
        self._security_lbl.setText(f"Security: {network['security']}")
        self._status_lbl.setText("Status: Connected" if network["connected"] else "Status: Not connected")
        self._connect_btn.setText("Disconnect" if network["connected"] else "Connect")
        self.setVisible(True)


class WifiTab(QWidget):
    def __init__(self):
        super().__init__()
        self._thread = None
        self._networks = []
        self._build_ui()
        self._scan()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(QLabel("Wi-Fi"))
        header.addStretch()
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.clicked.connect(self._scan)
        header.addWidget(self._reload_btn)
        root.addLayout(header)

        self._status_lbl = QLabel("Scanning…")
        root.addWidget(self._status_lbl)

        body = QHBoxLayout()
        body.setSpacing(0)

        self._list = QListWidget()
        self._list.setFrameShape(QFrame.NoFrame)
        self._list.currentRowChanged.connect(self._on_select)
        body.addWidget(self._list, stretch=1)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        body.addWidget(sep)

        self._detail = _DetailPanel()
        self._detail.connect_requested.connect(self._connect)
        self._detail.forget_requested.connect(self._forget)
        body.addWidget(self._detail, stretch=1)

        root.addLayout(body, stretch=1)

    def _scan(self):
        if self._thread and self._thread.isRunning():
            return
        self._reload_btn.setEnabled(False)
        self._status_lbl.setText("Scanning…")
        self._list.clear()
        self._detail.setVisible(False)
        self._networks = []
        self._thread = _ScanThread()
        self._thread.done.connect(self._on_done)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _on_done(self, networks):
        self._networks = networks
        self._reload_btn.setEnabled(True)
        if not networks:
            self._status_lbl.setText("No networks found")
            return
        self._status_lbl.setText(f"{len(networks)} network(s) found")
        for net in networks:
            label = net["ssid"] + ("  - Connected" if net["connected"] else "")
            self._list.addItem(QListWidgetItem(label))

    def _on_error(self, msg):
        self._reload_btn.setEnabled(True)
        self._status_lbl.setText(f"Error: {msg}")

    def _on_select(self, row):
        if 0 <= row < len(self._networks):
            self._detail.show_network(self._networks[row])

    def _connect(self, network):
        if network["connected"]:
            _run(["nmcli", "connection", "down", "id", network["ssid"]])
            self._scan()
            return

        if _saved_connection(network["ssid"]):
            cmd = ["nmcli", "connection", "up", "id", network["ssid"]]
        else:
            password = None
            if network["security"] != "Open":
                password, ok = QInputDialog.getText(
                    self, "Connect", f"Password for {network['ssid']}:",
                    QLineEdit.EchoMode.Password
                )
                if not ok:
                    return
            cmd = ["nmcli", "device", "wifi", "connect", network["ssid"]]
            if password:
                cmd += ["password", password]

        self._status_lbl.setText(f"Connecting to {network['ssid']}…")
        self._reload_btn.setEnabled(False)
        threading.Thread(target=self._do_connect, args=(cmd,), daemon=True).start()

    def _do_connect(self, cmd):
        _run(cmd)
        QMetaObject.invokeMethod(self, "_scan", Qt.ConnectionType.QueuedConnection)

    def _forget(self, network):
        reply = QMessageBox.question(
            self, "Forget Network",
            f"Forget \"{network['ssid']}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            _run(["nmcli", "connection", "delete", "id", network["ssid"]])
            self._scan()
