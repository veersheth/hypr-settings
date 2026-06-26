import configparser
import os
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QFontComboBox, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
from common import run, separator, make_centered, ToggleSwitch

GTK3 = os.path.expanduser("~/.config/gtk-3.0/settings.ini")
GTK4 = os.path.expanduser("~/.config/gtk-4.0/settings.ini")


def _theme_dirs():
    dirs = [os.path.expanduser("~/.local/share/icons")]
    for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        if d:
            dirs.append(os.path.join(d, "icons"))
    return dirs


def _read_ini(path):
    cp = configparser.RawConfigParser()
    try:
        cp.read(path, encoding="utf-8")
    except Exception:
        pass
    return dict(cp["Settings"]) if cp.has_section("Settings") else {}


def _update_ini(path, updates):
    cp = configparser.RawConfigParser()
    try:
        cp.read(path, encoding="utf-8")
    except Exception:
        pass
    if not cp.has_section("Settings"):
        cp.add_section("Settings")
    for k, v in updates.items():
        cp.set("Settings", k, str(v))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        cp.write(f)


def _scan_icon_themes():
    seen = {}
    for base in _theme_dirs():
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            if entry in seen:
                continue
            index = os.path.join(base, entry, "index.theme")
            if not os.path.isfile(index):
                continue
            cp = configparser.RawConfigParser()
            try:
                cp.read(index, encoding="utf-8")
            except Exception:
                continue
            if not cp.has_section("Icon Theme"):
                continue
            if cp.get("Icon Theme", "Hidden", fallback="false").lower() == "true":
                continue
            if not cp.get("Icon Theme", "Directories", fallback="").strip():
                continue
            seen[entry] = cp.get("Icon Theme", "Name", fallback=entry)
    return sorted([(v, k) for k, v in seen.items()], key=lambda x: x[0].lower())


def _scan_cursor_themes():
    seen = {}
    for base in _theme_dirs():
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            if entry in seen:
                continue
            if not os.path.isdir(os.path.join(base, entry, "cursors")):
                continue
            index = os.path.join(base, entry, "index.theme")
            name = entry
            if os.path.isfile(index):
                cp = configparser.RawConfigParser()
                try:
                    cp.read(index, encoding="utf-8")
                    if cp.get("Icon Theme", "Hidden", fallback="false").lower() == "true":
                        continue
                    name = cp.get("Icon Theme", "Name", fallback=entry)
                except Exception:
                    pass
            seen[entry] = name
    return sorted([(v, k) for k, v in seen.items()], key=lambda x: x[0].lower())


def _parse_font(s):
    parts = s.rsplit(" ", 1)
    if len(parts) == 2:
        try:
            return parts[0].strip(), int(parts[1])
        except ValueError:
            pass
    return s.strip(), 11


def _gsettings(key, value):
    run(["gsettings", "set", "org.gnome.desktop.interface", key, str(value)])


class _LoadThread(QThread):
    done = Signal(dict, list, list)

    def run(self):
        settings = _read_ini(GTK3)
        self.done.emit(settings, _scan_icon_themes(), _scan_cursor_themes())


class AppearanceTab(QWidget):
    def __init__(self):
        super().__init__()
        self._busy = False
        self._load_thread = None
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(make_centered(self))
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Appearance")
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

        def row(label, widget):
            h = QHBoxLayout()
            h.setSpacing(10)
            lbl = QLabel(label)
            lbl.setFixedWidth(160)
            lbl.setObjectName("fieldLabel")
            h.addWidget(lbl)
            h.addWidget(widget, stretch=1)
            root.addLayout(h)

        self._toggle = ToggleSwitch()
        self._toggle.toggled.connect(self._on_color)

        scheme_container = QWidget()
        scheme_layout = QHBoxLayout(scheme_container)
        scheme_layout.setContentsMargins(0, 0, 0, 0)
        scheme_layout.setSpacing(10)
        scheme_layout.addWidget(QLabel("Light"))
        scheme_layout.addWidget(self._toggle)
        scheme_layout.addWidget(QLabel("Dark"))
        scheme_layout.addStretch()
        row("Color Scheme", scheme_container)

        root.addWidget(separator())

        self._icon_combo = QComboBox()
        self._icon_combo.currentIndexChanged.connect(self._on_icon)
        row("GTK Icon Theme", self._icon_combo)

        self._cursor_combo = QComboBox()
        self._cursor_combo.currentIndexChanged.connect(self._on_cursor_theme)
        row("GTK Cursor Theme", self._cursor_combo)

        root.addWidget(separator())

        self._font_combo = QFontComboBox()
        self._font_combo.currentFontChanged.connect(self._on_font)
        self._font_size = QSpinBox()
        self._font_size.setRange(6, 72)
        self._font_size.setFixedWidth(70)
        self._font_size.valueChanged.connect(self._on_font_size)
        font_container = QWidget()
        font_layout = QHBoxLayout(font_container)
        font_layout.setContentsMargins(0, 0, 0, 0)
        font_layout.setSpacing(6)
        font_layout.addWidget(self._font_combo, stretch=1)
        font_layout.addWidget(self._font_size)
        row("GTK Font", font_container)

        root.addStretch()

    def _load(self):
        if self._load_thread and self._load_thread.isRunning():
            return
        self._reload_btn.setEnabled(False)
        self._status_lbl.setText("Loading…")
        self._load_thread = _LoadThread()
        self._load_thread.done.connect(self._on_done)
        self._load_thread.start()

    def _on_done(self, settings, icon_themes, cursor_themes):
        self._reload_btn.setEnabled(True)
        self._busy = True

        dark = settings.get("gtk-application-prefer-dark-theme", "").lower()
        self._toggle.set_on(dark in ("1", "true"), silent=True)

        self._icon_combo.clear()
        self._icon_combo.addItem("-", "")
        for name, key in icon_themes:
            self._icon_combo.addItem(name, key)
        idx = self._icon_combo.findData(settings.get("gtk-icon-theme-name", ""))
        self._icon_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self._cursor_combo.clear()
        self._cursor_combo.addItem("-", "")
        for name, key in cursor_themes:
            self._cursor_combo.addItem(name, key)
        idx = self._cursor_combo.findData(settings.get("gtk-cursor-theme-name", ""))
        self._cursor_combo.setCurrentIndex(idx if idx >= 0 else 0)

        font_name, font_size = _parse_font(settings.get("gtk-font-name", "Sans 11"))
        self._font_combo.setCurrentFont(QFont(font_name))
        self._font_size.setValue(font_size)

        self._busy = False
        self._status_lbl.setText(
            f"{len(icon_themes)} icon theme(s)  ·  {len(cursor_themes)} cursor theme(s)"
        )

    def _on_color(self, is_dark):
        if self._busy:
            return
        dark_val = "true" if is_dark else "false"
        scheme = "prefer-dark" if is_dark else "prefer-light"
        _update_ini(GTK3, {"gtk-application-prefer-dark-theme": dark_val})
        _update_ini(GTK4, {"gtk-application-prefer-dark-theme": dark_val, "gtk-color-scheme": scheme})
        _gsettings("color-scheme", scheme)

    def _on_icon(self, _):
        if self._busy:
            return
        val = self._icon_combo.currentData()
        if val:
            _update_ini(GTK3, {"gtk-icon-theme-name": val})
            _update_ini(GTK4, {"gtk-icon-theme-name": val})
            _gsettings("icon-theme", val)

    def _on_cursor_theme(self, _):
        if self._busy:
            return
        val = self._cursor_combo.currentData()
        if val:
            _update_ini(GTK3, {"gtk-cursor-theme-name": val})
            _update_ini(GTK4, {"gtk-cursor-theme-name": val})
            _gsettings("cursor-theme", val)

    def _on_font(self, _):
        if not self._busy:
            self._save_font()

    def _on_font_size(self, _):
        if not self._busy:
            self._save_font()

    def _save_font(self):
        font_str = f"{self._font_combo.currentFont().family()} {self._font_size.value()}"
        _update_ini(GTK3, {"gtk-font-name": font_str})
        _update_ini(GTK4, {"gtk-font-name": font_str})
        _gsettings("font-name", f"'{font_str}'")
