import re
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)
from common import run, separator


def _wifi_device():
    out, _ = run(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "wifi":
            return parts[0]
    return None


def _wifi_enabled():
    out, _ = run(["nmcli", "radio", "wifi"])
    return out.strip() == "enabled"


def _saved_connection(ssid):
    out, _ = run(["nmcli", "-t", "-f", "NAME", "connection", "show"])
    return ssid in out.splitlines()


def _get_autoconnect(ssid):
    out, _ = run(["nmcli", "-t", "-f", "connection.autoconnect",
                   "connection", "show", "id", ssid])
    for line in out.splitlines():
        if line.startswith("connection.autoconnect:"):
            return line.split(":", 1)[1].strip().lower() == "yes"
    return False


def _get_connection_info(device):
    out, _ = run(["nmcli", "-t", "-f", "IP4.ADDRESS,IP4.GATEWAY,IP4.DNS",
                   "device", "show", device])
    info = {}
    dns_entries = []
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if not val or val == "--":
            continue
        if re.match(r"IP4\.ADDRESS\[1\]", key):
            parts = val.split("/")
            info["ip"] = parts[0]
            if len(parts) == 2:
                prefix = int(parts[1])
                mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
                info["subnet"] = ".".join(
                    str((mask >> (8 * i)) & 0xFF) for i in [3, 2, 1, 0]
                )
        elif key == "IP4.GATEWAY":
            info["gateway"] = val
        elif re.match(r"IP4\.DNS\[", key):
            dns_entries.append(val)
    if dns_entries:
        info["dns"] = ", ".join(dns_entries)
    return info


def _parse_nmcli_line(line):
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
        "security": security.strip() or "Open",
        "connected": active.strip().lower() == "yes",
    }


# threads

class _ScanThread(QThread):
    done = Signal(list)
    error = Signal(str)

    def run(self):
        out, ok = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,ACTIVE",
                         "device", "wifi", "list", "--rescan", "auto"])
        if not ok and not out:
            self.error.emit("nmcli unavailable — is NetworkManager running?")
            return
        networks, seen = [], set()
        for line in out.splitlines():
            net = _parse_nmcli_line(line)
            if net and net["ssid"] not in seen:
                seen.add(net["ssid"])
                networks.append(net)
        networks.sort(key=lambda n: (-n["connected"], -n["signal"]))
        self.done.emit(networks)


class _ConnectThread(QThread):
    done = Signal(bool, str)

    def __init__(self, cmd):
        super().__init__()
        self._cmd = cmd

    def run(self):
        out, ok = run(self._cmd)
        self.done.emit(ok, out)


class _DetailPanel(QWidget):
    action_done = Signal()

    def __init__(self):
        super().__init__()
        self._network = None
        self._device = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 4, 0, 0)
        root.setSpacing(8)
        root.setAlignment(Qt.AlignTop)

        # Network identity
        self._ssid_lbl = QLabel()
        self._ssid_lbl.setObjectName("detailTitle")
        root.addWidget(self._ssid_lbl)
        self._signal_lbl = QLabel()
        self._security_lbl = QLabel()
        root.addWidget(self._signal_lbl)
        root.addWidget(self._security_lbl)

        # Connection details (connected only)
        self._conn_sep = separator()
        root.addWidget(self._conn_sep)
        self._ip_lbl = QLabel()
        self._subnet_lbl = QLabel()
        self._gateway_lbl = QLabel()
        self._dns_lbl = QLabel()
        for w in (self._ip_lbl, self._subnet_lbl, self._gateway_lbl, self._dns_lbl):
            root.addWidget(w)

        # Auto-connect (saved networks)
        self._auto_sep = separator()
        root.addWidget(self._auto_sep)
        self._autoconnect_cb = QCheckBox("Auto-connect")
        self._autoconnect_cb.stateChanged.connect(self._toggle_autoconnect)
        root.addWidget(self._autoconnect_cb)

        # Actions
        root.addWidget(separator())
        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton()
        self._connect_btn.clicked.connect(self._on_connect)
        self._forget_btn = QPushButton("Forget")
        self._forget_btn.clicked.connect(self._on_forget)
        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._forget_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._status_lbl = QLabel()
        root.addWidget(self._status_lbl)
        root.addStretch()
        self.setVisible(False)

    def show_network(self, network: dict, device: str | None):
        self._network = network
        self._device = device
        saved = _saved_connection(network["ssid"])

        self._ssid_lbl.setText(network["ssid"])
        self._signal_lbl.setText(f"Signal strength: {network['signal']}%")
        lock = "  🔒" if network["security"] != "Open" else ""
        self._security_lbl.setText(f"Security: {network['security']}{lock}")
        self._status_lbl.setText("")

        # Connection info
        connected = network["connected"]
        self._conn_sep.setVisible(connected)
        self._ip_lbl.setVisible(connected)
        self._subnet_lbl.setVisible(connected)
        self._gateway_lbl.setVisible(connected)
        self._dns_lbl.setVisible(connected)
        if connected and device:
            info = _get_connection_info(device)
            self._ip_lbl.setText(f"IP Address: {info.get('ip', '—')}")
            self._subnet_lbl.setText(f"Subnet Mask: {info.get('subnet', '—')}")
            self._gateway_lbl.setText(f"Gateway: {info.get('gateway', '—')}")
            self._dns_lbl.setText(f"DNS: {info.get('dns', '—')}")

        # Auto-connect
        self._auto_sep.setVisible(saved)
        self._autoconnect_cb.setVisible(saved)
        if saved:
            self._autoconnect_cb.blockSignals(True)
            self._autoconnect_cb.setChecked(_get_autoconnect(network["ssid"]))
            self._autoconnect_cb.blockSignals(False)

        # Buttons
        self._connect_btn.setText("Disconnect" if connected else "Connect")
        self._forget_btn.setVisible(saved)

        self.setVisible(True)

    def _toggle_autoconnect(self, state):
        if self._network:
            val = "yes" if bool(state) else "no"
            run(["nmcli", "connection", "modify", "id",
                  self._network["ssid"], "connection.autoconnect", val])

    def _on_connect(self):
        net = self._network
        if not net:
            return

        if net["connected"]:
            self._set_status("Disconnecting…")
            run(["nmcli", "connection", "down", "id", net["ssid"]])
            self.action_done.emit()
            return

        if _saved_connection(net["ssid"]):
            cmd = ["nmcli", "connection", "up", "id", net["ssid"]]
        else:
            password = None
            if net["security"] != "Open":
                password, ok = QInputDialog.getText(
                    self, "Connect", f"Password for {net['ssid']}:",
                    QLineEdit.EchoMode.Password
                )
                if not ok:
                    return
            cmd = ["nmcli", "device", "wifi", "connect", net["ssid"]]
            if password:
                cmd += ["password", password]

        self._set_status(f"Connecting…")
        self._connect_btn.setEnabled(False)
        t = _ConnectThread(cmd)
        t.done.connect(self._on_connect_done)
        t.start()
        self._thread = t

    def _on_connect_done(self, ok, out):
        self._connect_btn.setEnabled(True)
        if ok:
            self.action_done.emit()
        else:
            self._set_status(f"Failed: {out.splitlines()[-1] if out else 'unknown error'}")

    def _on_forget(self):
        net = self._network
        if not net:
            return
        reply = QMessageBox.question(
            self, "Forget Network",
            f"Forget \"{net['ssid']}\"?\nYou will need to enter the password again to reconnect.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            run(["nmcli", "connection", "delete", "id", net["ssid"]])
            self.action_done.emit()

    def _set_status(self, text):
        self._status_lbl.setText(text)


# main

class WifiTab(QWidget):
    def __init__(self):
        super().__init__()
        self._scan_thread = None
        self._networks = []
        self._build_ui()
        self._refresh_toggle()
        self._scan()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Wi-Fi")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self._toggle_btn = QPushButton()
        self._toggle_btn.setFixedWidth(120)
        self._toggle_btn.clicked.connect(self._toggle_wifi)
        header.addWidget(self._toggle_btn)
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.clicked.connect(self._scan)
        header.addWidget(self._reload_btn)
        root.addLayout(header)

        self._status_lbl = QLabel("Scanning…")
        self._status_lbl.setObjectName("statusLabel")
        root.addWidget(self._status_lbl)

        # Body
        body = QHBoxLayout()
        body.setSpacing(0)

        # Left: network list + hidden network button
        left = QVBoxLayout()
        left.setSpacing(6)
        left.setContentsMargins(0, 0, 16, 0)
        self._list = QListWidget()
        self._list.setFrameShape(QFrame.NoFrame)
        self._list.currentRowChanged.connect(self._on_select)
        left.addWidget(self._list)

        hidden_btn = QPushButton("Connect to hidden network…")
        hidden_btn.clicked.connect(self._connect_hidden)
        left.addWidget(hidden_btn)

        body.addLayout(left, stretch=1)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        body.addWidget(sep)

        # Right: detail panel
        self._detail = _DetailPanel()
        self._detail.action_done.connect(self._scan)
        body.addWidget(self._detail, stretch=1)

        root.addLayout(body, stretch=1)

    def _refresh_toggle(self):
        enabled = _wifi_enabled()
        self._toggle_btn.setText("Disable Wi-Fi" if enabled else "Enable Wi-Fi")
        self._reload_btn.setEnabled(enabled)

    def _toggle_wifi(self):
        state = "off" if _wifi_enabled() else "on"
        run(["nmcli", "radio", "wifi", state])
        self._refresh_toggle()
        if state == "on":
            self._scan()
        else:
            self._list.clear()
            self._detail.setVisible(False)
            self._status_lbl.setText("Wi-Fi disabled")

    def _scan(self):
        if self._scan_thread and self._scan_thread.isRunning():
            return
        if not _wifi_enabled():
            return
        self._reload_btn.setEnabled(False)
        self._status_lbl.setText("Scanning…")
        self._list.clear()
        self._detail.setVisible(False)
        self._networks = []
        self._scan_thread = _ScanThread()
        self._scan_thread.done.connect(self._on_done)
        self._scan_thread.error.connect(self._on_error)
        self._scan_thread.start()

    def _on_done(self, networks):
        self._networks = networks
        self._reload_btn.setEnabled(True)
        if not networks:
            self._status_lbl.setText("No networks found")
            return
        self._status_lbl.setText(f"{len(networks)} network(s) found")
        for net in networks:
            parts = [f"{net['signal']}%", net["ssid"]]
            if net["security"] != "Open":
                parts.append("🔒")
            if net["connected"]:
                parts.append("Connected")
            self._list.addItem(QListWidgetItem("   ".join(parts)))

    def _on_error(self, msg):
        self._reload_btn.setEnabled(True)
        self._status_lbl.setText(f"Error: {msg}")

    def _on_select(self, row):
        if 0 <= row < len(self._networks):
            device = _wifi_device()
            self._detail.show_network(self._networks[row], device)

    def _connect_hidden(self):
        ssid, ok = QInputDialog.getText(self, "Hidden Network", "Network name (SSID):")
        if not ok or not ssid.strip():
            return
        ssid = ssid.strip()
        password, ok = QInputDialog.getText(
            self, "Hidden Network", f"Password for \"{ssid}\":",
            QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        cmd = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            cmd += ["password", password]
        cmd += ["hidden", "yes"]
        self._status_lbl.setText(f"Connecting to {ssid}…")
        self._reload_btn.setEnabled(False)
        t = _ConnectThread(cmd)
        t.done.connect(lambda ok, _: self._scan())
        t.start()
        self._connect_thread = t

