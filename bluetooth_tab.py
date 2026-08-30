import re
import subprocess
import time
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel,
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


class _PowerThread(QThread):
    # succeeded, hint: "" | "service_needed"
    done = Signal(bool, str)

    def __init__(self, turn_on):
        super().__init__()
        self._turn_on = turn_on

    def run(self):
        if self._turn_on:
            # Step 1: clear any software rfkill block
            run(["rfkill", "unblock", "bluetooth"])
            run(["rfkill", "unblock", "all"])
            run(["bluetoothctl", "power", "on"])
            if _bt_enabled():
                self.done.emit(True, "")
                return

            # Step 2: bluetooth daemon might not be running — try starting it
            # (works without root when polkit/systemd allows it for the session)
            subprocess.run(
                ["systemctl", "start", "bluetooth"],
                capture_output=True, timeout=8,
            )
            time.sleep(1.5)
            run(["bluetoothctl", "power", "on"])
            if _bt_enabled():
                self.done.emit(True, "")
            else:
                self.done.emit(False, "service_needed")
        else:
            run(["bluetoothctl", "power", "off"])
            self.done.emit(not _bt_enabled(), "")


class _ServiceThread(QThread):
    """Start the bluetooth systemd service with elevated privileges."""
    done = Signal(bool, str)

    def run(self):
        try:
            r = subprocess.run(
                ["pkexec", "systemctl", "start", "bluetooth"],
                capture_output=True, text=True, timeout=30,
            )
        except FileNotFoundError:
            self.done.emit(False, "pkexec not found")
            return
        except subprocess.TimeoutExpired:
            self.done.emit(False, "timed out")
            return
        if r.returncode != 0:
            self.done.emit(False, r.stderr.strip() or "failed")
            return
        time.sleep(1.5)
        run(["bluetoothctl", "power", "on"])
        self.done.emit(_bt_enabled(), "")


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


class _DeviceDialog(QDialog):
    def __init__(self, device: dict, parent=None):
        super().__init__(parent)
        self._device = device
        self._thread = None

        self.setWindowTitle(device["name"])
        self.setMinimumWidth(380)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)

        name_lbl = QLabel(self._device["name"])
        name_lbl.setObjectName("detailTitle")
        root.addWidget(name_lbl)

        root.addWidget(QLabel(f"Address: {self._device['mac']}"))
        root.addWidget(QLabel(f"Type: {self._device['icon'] or '—'}"))
        root.addWidget(QLabel(f"Paired: {'Yes' if self._device['paired'] else 'No'}"))
        root.addWidget(QLabel(f"Connected: {'Yes' if self._device['connected'] else 'No'}"))

        root.addWidget(separator())

        self._trust_cb = QCheckBox("Trusted")
        self._trust_cb.setChecked(self._device["trusted"])
        self._trust_cb.stateChanged.connect(self._toggle_trust)
        root.addWidget(self._trust_cb)

        root.addWidget(separator())

        self._status_lbl = QLabel()
        self._status_lbl.setObjectName("statusLabel")
        root.addWidget(self._status_lbl)

        btn_row = QHBoxLayout()

        if self._device["paired"]:
            self._connect_btn = QPushButton(
                "Disconnect" if self._device["connected"] else "Connect"
            )
            self._connect_btn.clicked.connect(self._on_connect)
            btn_row.addWidget(self._connect_btn)
        else:
            self._connect_btn = None

        self._pair_btn = QPushButton("Unpair" if self._device["paired"] else "Pair")
        self._pair_btn.clicked.connect(self._on_pair)
        btn_row.addWidget(self._pair_btn)

        if self._device["paired"]:
            remove_btn = QPushButton("Remove")
            remove_btn.clicked.connect(self._on_remove)
            btn_row.addWidget(remove_btn)

        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    def _run_action(self, cmd, status_msg):
        self._status_lbl.setText(status_msg)
        if self._connect_btn:
            self._connect_btn.setEnabled(False)
        self._pair_btn.setEnabled(False)
        t = _ActionThread(cmd)
        t.done.connect(self._on_action_done)
        t.start()
        self._thread = t

    def _on_action_done(self, ok, out):
        if ok:
            self.accept()
        else:
            if self._connect_btn:
                self._connect_btn.setEnabled(True)
            self._pair_btn.setEnabled(True)
            self._status_lbl.setText(
                f"Failed: {out.splitlines()[-1] if out else 'unknown error'}"
            )

    def _on_connect(self):
        if self._device["connected"]:
            self._run_action(["bluetoothctl", "disconnect", self._device["mac"]], "Disconnecting…")
        else:
            self._run_action(["bluetoothctl", "connect", self._device["mac"]], "Connecting…")

    def _on_pair(self):
        if self._device["paired"]:
            self._run_action(["bluetoothctl", "remove", self._device["mac"]], "Removing…")
        else:
            self._run_action(["bluetoothctl", "pair", self._device["mac"]], "Pairing…")

    def _on_remove(self):
        reply = QMessageBox.question(
            self, "Remove Device",
            f"Remove \"{self._device['name']}\"?\nYou will need to pair it again to reconnect.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_action(["bluetoothctl", "remove", self._device["mac"]], "Removing…")

    def _toggle_trust(self, state):
        cmd = "trust" if bool(state) else "untrust"
        self._run_action(
            ["bluetoothctl", cmd, self._device["mac"]],
            "Trusting…" if bool(state) else "Untrusting…",
        )


class BluetoothTab(QWidget):
    def __init__(self):
        super().__init__()
        self._load_thread    = None
        self._scan_thread    = None
        self._power_thread   = None
        self._service_thread = None
        self._devices        = []
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

        self._force_btn = QPushButton("Start Bluetooth service (requires root)…")
        self._force_btn.clicked.connect(self._force_start_service)
        self._force_btn.setVisible(False)
        root.addWidget(self._force_btn)

        self._list = NavList()
        self._list.setFrameShape(QFrame.NoFrame)
        self._list.itemClicked.connect(self._on_select)
        root.addWidget(self._list, stretch=1)

    def _refresh_toggle(self):
        enabled = _bt_enabled()
        self._bt_switch.set_on(enabled, silent=True)
        self._scan_btn.setEnabled(enabled)

    def _toggle_bt(self, turn_on):
        self._bt_switch.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._force_btn.setVisible(False)
        self._status_lbl.setText("Enabling Bluetooth…" if turn_on else "Disabling Bluetooth…")
        if not turn_on:
            self._list.clear()
        self._power_thread = _PowerThread(turn_on)
        self._power_thread.done.connect(lambda ok, hint: self._on_power_done(turn_on, ok, hint))
        self._power_thread.start()

    def _on_power_done(self, wanted_on, succeeded, hint):
        self._bt_switch.setEnabled(True)
        self._refresh_toggle()
        if wanted_on:
            if succeeded:
                self._force_btn.setVisible(False)
                QTimer.singleShot(600, self._load)
            elif hint == "service_needed":
                self._status_lbl.setText("Bluetooth service is not running")
                self._force_btn.setVisible(True)
            else:
                self._status_lbl.setText("Failed to enable Bluetooth")
        else:
            self._status_lbl.setText("Bluetooth powered off")

    def _force_start_service(self):
        if self._service_thread and self._service_thread.isRunning():
            return
        self._force_btn.setEnabled(False)
        self._bt_switch.setEnabled(False)
        self._status_lbl.setText("Starting Bluetooth service… (polkit prompt may appear)")
        self._service_thread = _ServiceThread()
        self._service_thread.done.connect(self._on_service_done)
        self._service_thread.start()

    def _on_service_done(self, succeeded, error):
        self._bt_switch.setEnabled(True)
        self._force_btn.setEnabled(True)
        self._refresh_toggle()
        if succeeded:
            self._force_btn.setVisible(False)
            self._status_lbl.setText("")
            QTimer.singleShot(600, self._load)
        else:
            self._status_lbl.setText(f"Failed to start service: {error or 'unknown error'}")

    def _load(self):
        if self._load_thread and self._load_thread.isRunning():
            return
        self._refresh_toggle()
        self._list.clear()
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

    def _on_select(self, item):
        row = self._list.row(item)
        if 0 <= row < len(self._devices):
            dlg = _DeviceDialog(self._devices[row], self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._load()
            self._list.clearSelection()
