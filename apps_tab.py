import glob
import os
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from common import run, separator, make_centered

AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")

CATEGORIES = [
    ("Web Browser",     "x-scheme-handler/http",  ["x-scheme-handler/http", "x-scheme-handler/https", "text/html"]),
    ("Email Client",    "x-scheme-handler/mailto", ["x-scheme-handler/mailto"]),
    ("File Manager",    "inode/directory",         ["inode/directory"]),
    ("Text Editor",     "text/plain",              ["text/plain"]),
    ("Image Viewer",    "image/png",               ["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"]),
    ("Video Player",    "video/mp4",               ["video/mp4", "video/x-matroska", "video/webm"]),
    ("Music Player",    "audio/mpeg",              ["audio/mpeg", "audio/ogg", "audio/flac"]),
    ("PDF Viewer",      "application/pdf",         ["application/pdf"]),
    ("Archive Manager", "application/zip",         ["application/zip", "application/x-tar", "application/x-compressed-tar"]),
    ("Calendar",        "text/calendar",           ["text/calendar"]),
]


def _xdg_app_dirs():
    dirs = []
    xdg_data = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    for d in xdg_data.split(":"):
        if d:
            dirs.append(os.path.join(d, "applications"))
    dirs.append(os.path.expanduser("~/.local/share/applications"))
    return dirs


def _parse_desktop(path):
    result = {
        "name": None, "mimes": set(),
        "comment": "", "no_display": False, "enabled": True,
    }
    try:
        in_entry = False
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line == "[Desktop Entry]":
                    in_entry = True
                elif line.startswith("["):
                    in_entry = False
                if not in_entry:
                    continue
                if line.startswith("Name=") and result["name"] is None:
                    result["name"] = line[5:]
                elif line.startswith("MimeType="):
                    result["mimes"] = {m for m in line[9:].split(";") if m}
                elif line.startswith("Comment="):
                    result["comment"] = line[8:]
                elif line.startswith("NoDisplay="):
                    result["no_display"] = line[10:].lower() == "true"
                elif line.startswith("X-GNOME-Autostart-enabled="):
                    result["enabled"] = line[26:].lower() != "false"
    except OSError:
        return None
    return result if result["name"] else None


def _apply_default(desktop_id, mime_types):
    for mime in mime_types:
        run(["xdg-mime", "default", desktop_id, mime])


def _write_autostart_enabled(path, enabled):
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        key = "X-GNOME-Autostart-enabled="
        val = f"{key}{'true' if enabled else 'false'}"
        lines = content.splitlines()
        if any(l.startswith(key) for l in lines):
            lines = [val if l.startswith(key) else l for l in lines]
        else:
            new_lines = []
            for l in lines:
                new_lines.append(l)
                if l == "[Desktop Entry]":
                    new_lines.append(val)
            lines = new_lines
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass


def _delete_autostart(path):
    try:
        os.remove(path)
    except OSError:
        pass


class _LoadThread(QThread):
    done = Signal(dict, dict, list)
    error = Signal(str)

    def run(self):
        all_apps = {}
        seen = set()
        for d in _xdg_app_dirs():
            for path in glob.glob(os.path.join(d, "*.desktop")):
                did = os.path.basename(path)
                if did in seen:
                    continue
                seen.add(did)
                info = _parse_desktop(path)
                if info and not info["no_display"]:
                    all_apps[did] = info

        apps_by_mime = {}
        defaults = {}
        for _, query_mime, _ in CATEGORIES:
            apps_by_mime[query_mime] = sorted(
                [(info["name"], did) for did, info in all_apps.items()
                 if query_mime in info["mimes"]],
                key=lambda x: x[0].lower(),
            )
            out, _ = run(["xdg-mime", "query", "default", query_mime])
            defaults[query_mime] = out.strip()

        os.makedirs(AUTOSTART_DIR, exist_ok=True)
        autostart = []
        for path in sorted(glob.glob(os.path.join(AUTOSTART_DIR, "*.desktop"))):
            info = _parse_desktop(path)
            if info:
                autostart.append({
                    "path": path,
                    "name": info["name"],
                    "comment": info["comment"],
                    "enabled": info["enabled"],
                })

        self.done.emit(apps_by_mime, defaults, autostart)


def _section_label(text):
    lbl = QLabel(text)
    lbl.setObjectName("sectionTitle")
    return lbl


class AppsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._load_thread = None
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(make_centered(self))
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Apps")
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

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 4, 0, 0)
        self._content_layout.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidget(self._content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, stretch=1)

    def _load(self):
        if self._load_thread and self._load_thread.isRunning():
            return
        self._reload_btn.setEnabled(False)
        self._status_lbl.setText("Loading…")
        self._load_thread = _LoadThread()
        self._load_thread.done.connect(self._on_done)
        self._load_thread.error.connect(self._on_error)
        self._load_thread.start()

    def _on_error(self, msg):
        self._reload_btn.setEnabled(True)
        self._status_lbl.setText(f"Error: {msg}")

    def _on_done(self, apps_by_mime, defaults, autostart):
        self._reload_btn.setEnabled(True)

        layout = self._content_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Default Applications
        layout.addWidget(_section_label("Default Applications"))
        layout.addWidget(separator())

        for display_name, query_mime, set_mimes in CATEGORIES:
            matching = apps_by_mime.get(query_mime, [])
            current = defaults.get(query_mime, "")

            row = QHBoxLayout()
            row.setSpacing(10)
            lbl = QLabel(display_name)
            lbl.setFixedWidth(140)
            lbl.setObjectName("fieldLabel")
            row.addWidget(lbl)

            combo = QComboBox()
            combo.addItem("-", "")
            for app_name, did in matching:
                combo.addItem(app_name, did)

            combo.blockSignals(True)
            idx = combo.findData(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

            combo.currentIndexChanged.connect(
                lambda _, c=combo, mimes=set_mimes: self._on_default_change(c, mimes)
            )
            row.addWidget(combo, stretch=1)

            w = QWidget()
            w.setLayout(row)
            layout.addWidget(w)

        # Autostart
        layout.addSpacing(8)
        layout.addWidget(_section_label("Autostart"))
        layout.addWidget(separator())

        if not autostart:
            empty = QLabel("No autostart entries in ~/.config/autostart")
            empty.setObjectName("statusLabel")
            layout.addWidget(empty)
        else:
            for entry in autostart:
                layout.addWidget(self._make_autostart_row(entry))

        layout.addStretch()

        configured = sum(1 for q, _, _ in CATEGORIES if defaults.get(q))
        self._status_lbl.setText(
            f"{configured}/{len(CATEGORIES)} defaults set  ·  {len(autostart)} autostart entry/entries"
        )

    def _make_autostart_row(self, entry):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(10)

        cb = QCheckBox()
        cb.setChecked(entry["enabled"])
        cb.stateChanged.connect(
            lambda state, p=entry["path"]: _write_autostart_enabled(p, bool(state))
        )
        row.addWidget(cb)

        name_lbl = QLabel(entry["name"])
        if entry["comment"]:
            name_lbl.setToolTip(entry["comment"])
        row.addWidget(name_lbl, stretch=1)

        remove_btn = QPushButton("Remove")
        remove_btn.setFixedWidth(80)
        remove_btn.clicked.connect(lambda _, p=entry["path"], rw=w: self._on_remove(p, rw))
        row.addWidget(remove_btn)

        return w

    def _on_default_change(self, combo, set_mimes):
        did = combo.currentData()
        if did:
            _apply_default(did, set_mimes)

    def _on_remove(self, path, row_widget):
        _delete_autostart(path)
        row_widget.hide()
        row_widget.deleteLater()
