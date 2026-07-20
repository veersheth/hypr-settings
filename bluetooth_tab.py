import re
import subprocess
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel,
    QListWidgetItem, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)
from common import run, separator, make_centered, NavList, ToggleSwitch


def _run_bt_interactive(op: str, mac: str, timeout: int = 20) -> tuple[str, bool]:
    """Run a bluetoothctl pair/connect with a NoInputNoOutput agent registered."""
    script = f"agent NoInputNoOutput\ndefault-agent\n{op} {mac}\nquit\n"
    try:
        proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
        )
        out, _ = proc.communicate(input=script, timeout=timeout)
        ok = any(s in out for s in [
            "Connection successful", "Pairing successful",
            "Connected: yes", "Paired: yes",
        ])
        return out, ok
    except subprocess.TimeoutExpired:
        proc.kill()
        return "", False
    except FileNotFoundError:
        return "bluetoothctl not found", False


def _bt_enabled():
    out, _ = run(["bluetoothctl", "show"])
    return "Powered: yes" in out


def _parse_devices(out):
    devices = {}
    for line in out.splitlines():
        m = re.match(r"Device ([0-9A-F:]{17})\s+(.*)", line)
        if m:
            mac, name = m.group(1), m.group(2)
            devices[mac] = name
    return devices


def _device_info(mac):
    out, _ = run(["bluetoothctl", "info", mac])
    info = {"mac": mac, "name": mac, "paired": False,
            "connected": False, "trusted": False, "icon": ""}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            info["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Icon:"):
            info["icon"] = line.split(":", 1)[1].strip()
        elif line.startswith("Paired:"):
            info["paired"] = line.split(":", 1)[1].strip().lower() == "yes"
        elif line.startswith("Connected:"):
            info["connected"] = line.split(":", 1)[1].strip().lower() == "yes"
        elif line.startswith("Trusted:"):
            info["trusted"] = line.split(":", 1)[1].strip().lower() == "yes"
    return info


class _LoadThread(QThread):
    done = Signal(list)
    error = Signal(str)

    def run(self):
        if not _bt_enabled():
            self.error.emit("Bluetooth is powered off")
            return
        out, _ = run(["bluetoothctl", "devices"])
        macs = list(_parse_devices(out).keys())
        devices = [_device_info(mac) for mac in macs]
        devices.sort(key=lambda d: (-d["connected"], -d["paired"], d["name"].lower()))
        self.done.emit(devices)


class _ScanThread(QThread):
    done = Signal()

    def run(self):
        # scan for 8 seconds then stop
        try:
            proc = subprocess.Popen(
                ["bluetoothctl", "scan", "on"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.terminate()
        run(["bluetoothctl", "scan", "off"])
        self.done.emit()


class _ActionThread(QThread):
    done = Signal(bool, str)

    def __init__(self, cmd):
        super().__init__()
        self._cmd = cmd

    def run(self):
        cmd = self._cmd
        # pair and connect need an agent to handle confirmation dialogs
        if (len(cmd) >= 3 and cmd[0] == "bluetoothctl"
                and cmd[1] in ("connect", "pair")):
            out, ok = _run_bt_interactive(cmd[1], cmd[2])
        else:
            out, ok = run(cmd)
        self.done.emit(ok, out)


class _DetailPanel(QWidget):
    action_done = Signal()

    def __init__(self):
        super().__init__()
        self._device = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 4, 0, 0)
        root.setSpacing(8)
        root.setAlignment(Qt.AlignTop)

        self._name_lbl = QLabel()
        self._name_lbl.setObjectName("detailTitle")
        root.addWidget(self._name_lbl)

        self._mac_lbl = QLabel()
        self._icon_lbl = QLabel()
        root.addWidget(self._mac_lbl)
        root.addWidget(self._icon_lbl)

        root.addWidget(separator())

        self._paired_lbl = QLabel()
        self._connected_lbl = QLabel()
        root.addWidget(self._paired_lbl)
        root.addWidget(self._connected_lbl)

        root.addWidget(separator())

        self._trust_cb = QCheckBox("Trusted")
        self._trust_cb.stateChanged.connect(self._toggle_trust)
        root.addWidget(self._trust_cb)

        root.addWidget(separator())

        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton()
        self._connect_btn.clicked.connect(self._on_connect)
        self._pair_btn = QPushButton()
        self._pair_btn.clicked.connect(self._on_pair)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._on_remove)
        for btn in (self._connect_btn, self._pair_btn, self._remove_btn):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._status_lbl = QLabel()
        root.addWidget(self._status_lbl)
        root.addStretch()
        self.setVisible(False)

    def show_device(self, device: dict):
        self._device = device

        self._name_lbl.setText(device["name"])
        self._mac_lbl.setText(f"Address: {device['mac']}")
        self._icon_lbl.setText(f"Type: {device['icon'] or '—'}")
        self._paired_lbl.setText(f"Paired: {'Yes' if device['paired'] else 'No'}")
        self._connected_lbl.setText(f"Connected: {'Yes' if device['connected'] else 'No'}")
        self._status_lbl.setText("")

        self._trust_cb.blockSignals(True)
        self._trust_cb.setChecked(device["trusted"])
        self._trust_cb.blockSignals(False)

        self._connect_btn.setText("Disconnect" if device["connected"] else "Connect")
        self._connect_btn.setVisible(device["paired"])
        self._pair_btn.setText("Unpair" if device["paired"] else "Pair")
        self._remove_btn.setVisible(device["paired"])

        self.setVisible(True)

    def _set_status(self, text):
        self._status_lbl.setText(text)

    def _run_action(self, cmd, status_msg):
        self._set_status(status_msg)
        self._connect_btn.setEnabled(False)
        self._pair_btn.setEnabled(False)
        t = _ActionThread(cmd)
        t.done.connect(self._on_action_done)
        t.start()
        self._thread = t

    def _on_action_done(self, ok, out):
        self._connect_btn.setEnabled(True)
        self._pair_btn.setEnabled(True)
        if ok:
            self.action_done.emit()
        else:
            last_line = out.splitlines()[-1] if out else "unknown error"
            self._set_status(f"Failed: {last_line}")

    def _on_connect(self):
        if not self._device:
            return
        if self._device["connected"]:
            self._run_action(["bluetoothctl", "disconnect", self._device["mac"]], "Disconnecting…")
        else:
            self._run_action(["bluetoothctl", "connect", self._device["mac"]], "Connecting…")

    def _on_pair(self):
        if not self._device:
            return
        if self._device["paired"]:
            self._run_action(["bluetoothctl", "remove", self._device["mac"]], "Removing…")
        else:
            self._run_action(["bluetoothctl", "pair", self._device["mac"]], "Pairing…")

    def _on_remove(self):
        if not self._device:
            return
        reply = QMessageBox.question(
            self, "Remove Device",
            f"Remove \"{self._device['name']}\"?\nYou will need to pair it again to reconnect.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_action(["bluetoothctl", "remove", self._device["mac"]], "Removing…")

    def _toggle_trust(self, state):
        if not self._device:
            return
        cmd = "trust" if bool(state) else "untrust"
        self._run_action(["bluetoothctl", cmd, self._device["mac"]],
                         "Trusting…" if bool(state) else "Untrusting…")


class BluetoothTab(QWidget):
    def __init__(self):
        super().__init__()
        self._load_thread = None
        self._scan_thread = None
        self._devices = []
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(make_centered(self))
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Bluetooth")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self._bt_switch = ToggleSwitch()
        self._bt_switch.toggled.connect(self._toggle_bt)
        header.addWidget(self._bt_switch)
        self._scan_btn = QPushButton("Scan")
        self._scan_btn.clicked.connect(self._scan)
        header.addWidget(self._scan_btn)
        root.addLayout(header)

        self._status_lbl = QLabel("Loading...")
        self._status_lbl.setObjectName("statusLabel")
        root.addWidget(self._status_lbl)

        body = QHBoxLayout()
        body.setSpacing(0)

        self._list = NavList()
        self._list.setFrameShape(QFrame.NoFrame)
        self._list.currentRowChanged.connect(self._on_select)

        list_wrap = QVBoxLayout()
        list_wrap.setContentsMargins(0, 0, 16, 0)
        list_wrap.addWidget(self._list)
        body.addLayout(list_wrap, stretch=1)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        body.addWidget(sep)

        self._detail = _DetailPanel()
        self._detail.action_done.connect(self._load)
        body.addWidget(self._detail, stretch=1)

        root.addLayout(body, stretch=1)

    def _refresh_toggle(self):
        enabled = _bt_enabled()
        self._bt_switch.set_on(enabled, silent=True)
        self._scan_btn.setEnabled(enabled)

    def _toggle_bt(self, turn_on):
        self._bt_switch.setEnabled(False)

        if turn_on:
            self._status_lbl.setText("Enabling Bluetooth…")
            run(["rfkill", "unblock", "bluetooth"])
            _, ok = run(["bluetoothctl", "power", "on"])
            self._bt_switch.setEnabled(True)
            if not ok or not _bt_enabled():
                self._status_lbl.setText(
                    "Failed to enable Bluetooth — is bluetoothd running?"
                )
                self._refresh_toggle()
                return
            self._refresh_toggle()
            QTimer.singleShot(600, self._load)
        else:
            run(["bluetoothctl", "power", "off"])
            self._bt_switch.setEnabled(True)
            self._list.clear()
            self._detail.setVisible(False)
            self._refresh_toggle()
            self._status_lbl.setText("Bluetooth powered off")

    def _load(self):
        if self._load_thread and self._load_thread.isRunning():
            return
        self._refresh_toggle()
        self._list.clear()
        self._detail.setVisible(False)
        self._devices = []
        self._status_lbl.setText("Loading devices...")
        self._load_thread = _LoadThread()
        self._load_thread.done.connect(self._on_done)
        self._load_thread.error.connect(self._on_error)
        self._load_thread.start()

    def _scan(self):
        if self._scan_thread and self._scan_thread.isRunning():
            return
        self._scan_btn.setEnabled(False)
        self._scan_btn.setText("Scanning…")
        self._status_lbl.setText("Scanning for devices (8s)…")
        self._scan_thread = _ScanThread()
        self._scan_thread.done.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self):
        self._scan_btn.setEnabled(True)
        self._scan_btn.setText("Scan")
        self._load()

    def _on_done(self, devices):
        self._devices = devices
        if not devices:
            self._status_lbl.setText("No devices found")
            return
        paired = sum(1 for d in devices if d["paired"])
        self._status_lbl.setText(f"{len(devices)} device(s) - {paired} paired")
        for dev in devices:
            parts = [dev["name"]]
            if dev["connected"]:
                parts.append("Connected")
            elif dev["paired"]:
                parts.append("Paired")
            self._list.addItem(QListWidgetItem(" ".join(parts)))

    def _on_error(self, msg):
        self._status_lbl.setText(msg if msg == "Bluetooth is powered off" else f"Error: {msg}")

    def _on_select(self, row):
        if 0 <= row < len(self._devices):
            self._detail.show_device(self._devices[row])
