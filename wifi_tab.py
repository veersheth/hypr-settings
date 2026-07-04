import re
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)
from common import run, separator, make_centered, NavList, ToggleSwitch


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


def _is_enterprise(security: str) -> bool:
    return "802.1X" in security


def _get_enterprise_config(ssid: str) -> dict:
    fields = ",".join([
        "802-1x.eap", "802-1x.identity", "802-1x.anonymous-identity",
        "802-1x.phase2-auth", "802-1x.phase1-peapver",
        "802-1x.ca-cert", "802-1x.domain-suffix-match",
    ])
    out, ok = run(["nmcli", "-t", "-f", fields, "connection", "show", "id", ssid])
    if not ok:
        return {}
    config = {}
    for line in out.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            config[key.strip()] = val.strip()
    return config


# ── threads ──────────────────────────────────────────────────────────────────

class _ScanThread(QThread):
    done = Signal(list)
    error = Signal(str)

    def __init__(self, rescan=False):
        super().__init__()
        self._rescan = rescan

    def run(self):
        rescan = "yes" if self._rescan else "no"
        out, ok = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,ACTIVE",
                         "device", "wifi", "list", "--rescan", rescan])
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


class _MultiCmdThread(QThread):
    """Runs a sequence of commands, stopping on first failure."""
    done = Signal(bool, str)

    def __init__(self, cmds):
        super().__init__()
        self._cmds = cmds

    def run(self):
        last_out = ""
        for cmd in self._cmds:
            out, ok = run(cmd)
            last_out = out
            if not ok:
                self.done.emit(False, out)
                return
        self.done.emit(True, last_out)


# ── saved networks ────────────────────────────────────────────────────────────

class _SavedNetworksThread(QThread):
    done = Signal(list)

    def run(self):
        out, ok = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
        if not ok:
            self.done.emit([])
            return

        wifi_names = []
        for line in out.splitlines():
            parts = re.split(r'(?<!\\):', line, maxsplit=1)
            if len(parts) == 2 and parts[1].strip() == "802-11-wireless":
                wifi_names.append(parts[0].strip().replace("\\:", ":"))

        networks = []
        for name in wifi_names:
            km_out, _ = run([
                "nmcli", "-g", "802-11-wireless-security.key-mgmt",
                "connection", "show", "id", name,
            ])
            key_mgmt = km_out.strip()
            security = {
                "wpa-psk": "WPA Personal",
                "wpa-eap": "WPA Enterprise",
                "sae":     "WPA3",
            }.get(key_mgmt, "WPA Personal" if key_mgmt else "Open")
            networks.append({"name": name, "security": security})

        self.done.emit(networks)


class _SavedNetworksDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Saved Networks")
        self.setMinimumWidth(440)
        self.setMinimumHeight(420)
        self._deleted = False
        self._build_ui()
        self._load()

    def _build_ui(self):
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(8)

        self._status_lbl = QLabel("Loading…")
        self._status_lbl.setObjectName("statusLabel")
        vbox.addWidget(self._status_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setSpacing(4)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(self._list_widget)
        vbox.addWidget(scroll, stretch=1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        vbox.addLayout(btn_row)

    def _load(self):
        t = _SavedNetworksThread()
        t.done.connect(self._on_done)
        t.start()
        self._thread = t

    def _on_done(self, networks):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not networks:
            self._status_lbl.setText("No saved networks")
            return

        self._status_lbl.setText(f"{len(networks)} saved network(s)")
        for net in networks:
            self._list_layout.addWidget(self._make_row(net))

    def _make_row(self, net):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(10)

        name_lbl = QLabel(net["name"])
        h.addWidget(name_lbl, stretch=1)

        sec_lbl = QLabel(net["security"])
        sec_lbl.setObjectName("statusLabel")
        h.addWidget(sec_lbl)

        forget_btn = QPushButton("Forget")
        forget_btn.setFixedWidth(70)
        forget_btn.clicked.connect(lambda _, n=net["name"], r=row: self._forget(n, r))
        h.addWidget(forget_btn)

        return row

    def _forget(self, name, row_widget):
        reply = QMessageBox.question(
            self, "Forget Network",
            f"Forget \"{name}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        run(["nmcli", "connection", "delete", "id", name])
        row_widget.deleteLater()
        self._deleted = True
        remaining = sum(
            1 for i in range(self._list_layout.count())
            if self._list_layout.itemAt(i).widget()
        )
        self._status_lbl.setText(f"{remaining} saved network(s)")


# ── enterprise dialog ─────────────────────────────────────────────────────────

class _EnterpriseDialog(QDialog):
    _EAP        = ["PEAP", "TTLS", "TLS", "PWD"]
    _PEAP_INNER = ["MSCHAPv2", "MD5", "GTC"]
    _TTLS_INNER = ["MSCHAPv2", "MSCHAP", "PAP", "CHAP", "EAP-MD5", "EAP-GTC"]
    _PEAP_VERS  = ["Automatic", "0", "1"]

    _INNER_NM = {
        "MSCHAPv2": "mschapv2", "MD5": "md5", "GTC": "gtc",
        "MSCHAP": "mschap", "PAP": "pap", "CHAP": "chap",
        "EAP-MD5": "eap-md5", "EAP-GTC": "eap-gtc",
    }
    _INNER_DISPLAY = {v: k for k, v in _INNER_NM.items()}

    def __init__(self, ssid, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Connect to {ssid}")
        self.setMinimumWidth(500)
        self._vbox = QVBoxLayout(self)
        self._vbox.setSpacing(8)
        self._vbox.setContentsMargins(20, 20, 20, 16)
        self._build_ui()
        self._populate(config)

    def _field_row(self, label_text, widget):
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        lbl = QLabel(label_text)
        lbl.setFixedWidth(190)
        lbl.setObjectName("fieldLabel")
        h.addWidget(lbl)
        h.addWidget(widget, stretch=1)
        self._vbox.addWidget(container)
        return container

    def _build_ui(self):
        self._eap_combo = QComboBox()
        self._eap_combo.addItems(self._EAP)
        self._eap_combo.currentIndexChanged.connect(self._update_visibility)
        self._field_row("Authentication", self._eap_combo)

        self._anon_edit = QLineEdit()
        self._anon_edit.setPlaceholderText("anonymous")
        self._anon_row = self._field_row("Anonymous identity", self._anon_edit)

        self._domain_edit = QLineEdit()
        self._domain_edit.setPlaceholderText("e.g. unsw.edu.au")
        self._field_row("Domain", self._domain_edit)

        self._no_ca_cb = QCheckBox("No CA certificate is required")
        self._vbox.addWidget(self._no_ca_cb)

        self._peap_ver_combo = QComboBox()
        self._peap_ver_combo.addItems(self._PEAP_VERS)
        self._peap_ver_row = self._field_row("PEAP version", self._peap_ver_combo)

        self._inner_combo = QComboBox()
        self._inner_combo.addItems(self._PEAP_INNER)
        self._inner_row = self._field_row("Inner authentication", self._inner_combo)

        # TLS-only fields
        self._user_cert_edit = QLineEdit()
        self._user_cert_edit.setPlaceholderText("Path to user certificate (.pem/.crt)")
        self._user_cert_row = self._field_row("User certificate", self._user_cert_edit)

        self._priv_key_edit = QLineEdit()
        self._priv_key_edit.setPlaceholderText("Path to private key (.pem/.key)")
        self._priv_key_row = self._field_row("Private key", self._priv_key_edit)

        self._priv_key_pass_edit = QLineEdit()
        self._priv_key_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._priv_key_pass_row = self._field_row("Private key password", self._priv_key_pass_edit)

        self._vbox.addWidget(separator())

        self._user_edit = QLineEdit()
        self._user_row = self._field_row("Username", self._user_edit)

        self._pass_edit = QLineEdit()
        self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_row = self._field_row("Password", self._pass_edit)

        show_pw = QCheckBox("Show password")
        show_pw.stateChanged.connect(
            lambda s: self._pass_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if s else QLineEdit.EchoMode.Password
            )
        )
        self._vbox.addWidget(show_pw)

        self._vbox.addWidget(separator())

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        connect_btn = QPushButton("Connect")
        connect_btn.setDefault(True)
        connect_btn.clicked.connect(self.accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(connect_btn)
        self._vbox.addLayout(btns)

        self._update_visibility()

    def _update_visibility(self):
        eap = self._eap_combo.currentText()
        is_peap = eap == "PEAP"
        is_ttls = eap == "TTLS"
        is_tls  = eap == "TLS"
        is_pwd  = eap == "PWD"

        want = self._TTLS_INNER if is_ttls else self._PEAP_INNER
        if self._inner_combo.count() != len(want) or self._inner_combo.itemText(0) != want[0]:
            cur = self._inner_combo.currentText()
            self._inner_combo.blockSignals(True)
            self._inner_combo.clear()
            self._inner_combo.addItems(want)
            idx = self._inner_combo.findText(cur)
            self._inner_combo.setCurrentIndex(max(0, idx))
            self._inner_combo.blockSignals(False)

        self._anon_row.setVisible(not is_tls and not is_pwd)
        self._no_ca_cb.setVisible(not is_pwd)
        self._peap_ver_row.setVisible(is_peap)
        self._inner_row.setVisible(is_peap or is_ttls)
        self._user_cert_row.setVisible(is_tls)
        self._priv_key_row.setVisible(is_tls)
        self._priv_key_pass_row.setVisible(is_tls)
        self._user_row.setVisible(not is_tls)
        self._pass_row.setVisible(not is_tls)

    def _populate(self, config):
        if not config:
            return

        eap = config.get("802-1x.eap", "peap").lower().split(",")[0].strip()
        eap_display = {"peap": "PEAP", "ttls": "TTLS", "tls": "TLS", "pwd": "PWD"}.get(eap, "PEAP")
        idx = self._eap_combo.findText(eap_display)
        if idx >= 0:
            self._eap_combo.setCurrentIndex(idx)  # triggers _update_visibility

        phase2 = config.get("802-1x.phase2-auth", "").lower()
        inner_display = self._INNER_DISPLAY.get(phase2, "MSCHAPv2")
        idx = self._inner_combo.findText(inner_display)
        if idx >= 0:
            self._inner_combo.setCurrentIndex(idx)

        self._anon_edit.setText(config.get("802-1x.anonymous-identity", ""))
        self._domain_edit.setText(config.get("802-1x.domain-suffix-match", ""))
        self._user_edit.setText(config.get("802-1x.identity", ""))

        peap_ver = config.get("802-1x.phase1-peapver", "")
        ver_display = {"": "Automatic", "0": "0", "1": "1"}.get(peap_ver, "Automatic")
        idx = self._peap_ver_combo.findText(ver_display)
        if idx >= 0:
            self._peap_ver_combo.setCurrentIndex(idx)

        ca = config.get("802-1x.ca-cert", "")
        self._no_ca_cb.setChecked(not ca or ca == "--")

    def get_nmcli_args(self) -> list:
        eap = self._eap_combo.currentText().lower()
        args = ["wifi-sec.key-mgmt", "wpa-eap", "802-1x.eap", eap]

        domain = self._domain_edit.text().strip()
        if domain:
            args += ["802-1x.domain-suffix-match", domain]

        if eap in ("peap", "ttls", "pwd"):
            args += ["802-1x.identity", self._user_edit.text().strip()]
            args += ["802-1x.password", self._pass_edit.text()]
            anon = self._anon_edit.text().strip()
            if anon:
                args += ["802-1x.anonymous-identity", anon]

        if eap == "peap":
            inner_nm = self._INNER_NM.get(self._inner_combo.currentText(), "mschapv2")
            args += ["802-1x.phase2-auth", inner_nm]
            ver = self._peap_ver_combo.currentText()
            if ver != "Automatic":
                args += ["802-1x.phase1-peapver", ver]
        elif eap == "ttls":
            inner_nm = self._INNER_NM.get(self._inner_combo.currentText(), "mschapv2")
            args += ["802-1x.phase2-auth", inner_nm]
        elif eap == "tls":
            if self._user_cert_edit.text():
                args += ["802-1x.client-cert", self._user_cert_edit.text()]
            if self._priv_key_edit.text():
                args += ["802-1x.private-key", self._priv_key_edit.text()]
            if self._priv_key_pass_edit.text():
                args += ["802-1x.private-key-password", self._priv_key_pass_edit.text()]

        return args


# ── detail panel ──────────────────────────────────────────────────────────────

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

        ssid = net["ssid"]
        saved = _saved_connection(ssid)

        if _is_enterprise(net["security"]):
            config = _get_enterprise_config(ssid) if saved else {}
            dlg = _EnterpriseDialog(ssid, config, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            eap_args = dlg.get_nmcli_args()
            if saved:
                cmds = [
                    ["nmcli", "connection", "modify", "id", ssid] + eap_args,
                    ["nmcli", "connection", "up", "id", ssid],
                ]
            else:
                cmds = [
                    ["nmcli", "connection", "add", "type", "wifi",
                     "con-name", ssid, "ssid", ssid] + eap_args,
                    ["nmcli", "connection", "up", "id", ssid],
                ]
            self._set_status("Connecting…")
            self._connect_btn.setEnabled(False)
            t = _MultiCmdThread(cmds)
            t.done.connect(self._on_connect_done)
            t.start()
            self._thread = t
            return

        if saved:
            cmd = ["nmcli", "connection", "up", "id", ssid]
        else:
            password = None
            if net["security"] != "Open":
                password, ok = QInputDialog.getText(
                    self, "Connect", f"Password for {ssid}:",
                    QLineEdit.EchoMode.Password
                )
                if not ok:
                    return
            cmd = ["nmcli", "device", "wifi", "connect", ssid]
            if password:
                cmd += ["password", password]

        self._set_status("Connecting…")
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


# ── main tab ──────────────────────────────────────────────────────────────────

class WifiTab(QWidget):
    def __init__(self):
        super().__init__()
        self._scan_thread = None
        self._networks = []
        self._build_ui()
        self._refresh_toggle()
        self._scan()

    def _build_ui(self):
        root = QVBoxLayout(make_centered(self))
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Wi-Fi")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self._wifi_switch = ToggleSwitch()
        self._wifi_switch.toggled.connect(self._toggle_wifi)
        header.addWidget(self._wifi_switch)
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.clicked.connect(lambda: self._scan(rescan=True))
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
        self._list = NavList()
        self._list.setFrameShape(QFrame.NoFrame)
        self._list.currentRowChanged.connect(self._on_select)
        left.addWidget(self._list)

        bottom_btns = QHBoxLayout()
        bottom_btns.setSpacing(6)
        hidden_btn = QPushButton("Hidden network…")
        hidden_btn.clicked.connect(self._connect_hidden)
        bottom_btns.addWidget(hidden_btn)
        saved_btn = QPushButton("Saved networks…")
        saved_btn.clicked.connect(self._show_saved)
        bottom_btns.addWidget(saved_btn)
        left.addLayout(bottom_btns)

        body.addLayout(left, stretch=1)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        body.addWidget(sep)

        # Right: detail panel
        self._detail = _DetailPanel()
        self._detail.action_done.connect(lambda: self._scan(rescan=True))
        body.addWidget(self._detail, stretch=1)

        root.addLayout(body, stretch=1)

    def _refresh_toggle(self):
        enabled = _wifi_enabled()
        self._wifi_switch.set_on(enabled, silent=True)
        self._reload_btn.setEnabled(enabled)

    def _toggle_wifi(self, turn_on):
        run(["nmcli", "radio", "wifi", "on" if turn_on else "off"])
        self._reload_btn.setEnabled(turn_on)
        if turn_on:
            self._scan()
        else:
            self._list.clear()
            self._detail.setVisible(False)
            self._status_lbl.setText("Wi-Fi disabled")
        # Sync switch to actual state in case the command failed
        self._wifi_switch.set_on(_wifi_enabled(), silent=True)

    def _scan(self, rescan=False):
        if self._scan_thread and self._scan_thread.isRunning():
            return
        if not _wifi_enabled():
            return
        self._reload_btn.setEnabled(False)
        self._status_lbl.setText("Scanning…" if rescan else "Loading…")
        self._list.clear()
        self._detail.setVisible(False)
        self._networks = []
        self._scan_thread = _ScanThread(rescan=rescan)
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

    def _show_saved(self):
        dlg = _SavedNetworksDialog(self)
        dlg.exec()
        if dlg._deleted:
            self._scan(rescan=True)

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
