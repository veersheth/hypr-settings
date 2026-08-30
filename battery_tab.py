"""Battery status and history page."""
import glob
import os
import re
import subprocess
import tempfile
import time

from PySide6.QtCharts import (
    QAreaSeries, QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis,
)
from PySide6.QtCore import QDateTime, QMargins, QPointF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from common import make_centered, separator

_BAT_SYS      = "/sys/class/power_supply"
_UPOWER_DB    = "/var/lib/upower"
_POWERTOP_CSV = os.path.join(
    tempfile.gettempdir(),
    f"hypr-powertop-{os.getenv('USER', 'user')}.csv",
)


# ── sysfs / upower helpers ────────────────────────────────────────────────────

def _find_battery() -> str | None:
    try:
        for name in sorted(os.listdir(_BAT_SYS)):
            with open(os.path.join(_BAT_SYS, name, "type")) as f:
                if f.read().strip() == "Battery":
                    return name
    except OSError:
        pass
    return None


def _sysfs(bat: str, key: str) -> str:
    try:
        with open(os.path.join(_BAT_SYS, bat, key)) as f:
            return f.read().strip()
    except OSError:
        return ""


def _upower_info() -> dict:
    try:
        r = subprocess.run(
            ["upower", "-i", "/org/freedesktop/UPower/devices/DisplayDevice"],
            capture_output=True, text=True, timeout=5,
        )
        info: dict[str, str] = {}
        for line in r.stdout.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                info[k.strip()] = v.strip()
        return info
    except Exception:
        return {}


def _history_file(bat: str, kind: str = "charge") -> str | None:
    model = _sysfs(bat, "model_name").replace(" ", "_")
    if model:
        hits = glob.glob(os.path.join(_UPOWER_DB, f"history-{kind}-{model}*.dat"))
        if hits:
            return hits[0]
    hits = [
        p for p in glob.glob(os.path.join(_UPOWER_DB, f"history-{kind}-*.dat"))
        if not re.search(r'[0-9A-F]{2}:[0-9A-F]{2}', p, re.I)
    ]
    return hits[0] if hits else None


def _load_dat(path: str, hours: float) -> list[tuple[int, float, str]]:
    if not path or not os.path.exists(path):
        return []
    cutoff = int(time.time()) - int(hours * 3600)
    pts: list[tuple[int, float, str]] = []
    try:
        with open(path) as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    try:
                        ts, val = int(parts[0]), float(parts[1])
                        state = parts[2] if len(parts) > 2 else ""
                        if ts >= cutoff:
                            pts.append((ts * 1000, val, state))
                    except ValueError:
                        pass
    except OSError:
        pass
    return pts


# ── Powertop ─────────────────────────────────────────────────────────────────

def _parse_power_mw(s: str) -> float | None:
    """Convert "1.23 W" / "456 mW" / bare float to milliwatts."""
    s = s.strip()
    if not s:
        return None
    m = re.match(r"([\d.]+)\s*(m?[Ww]?)", s)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2).lower()
    if unit == "w":
        return val * 1000
    return val  # mW or bare (powertop uses mW as default)


def _parse_powertop_tunables(path: str) -> list[dict]:
    """Parse powertop --csv Tunables section → [{desc, status}]."""
    tunables = []
    in_section = False
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n\r")
                if line.strip() == "Tunables":
                    in_section = True
                    continue
                if not in_section:
                    continue
                parts = line.split(";")
                if len(parts) < 3:
                    continue
                desc, status = parts[0].strip(), parts[2].strip()
                if status.lower() in ("good", "bad") and desc and desc != "Description":
                    tunables.append({"desc": desc, "status": status.capitalize()})
    except OSError:
        pass
    return tunables


def _parse_powertop_consumers(path: str) -> list[dict]:
    """Parse powertop --csv Software Power consumers section → [{name, power_mw}]."""
    consumers: list[dict] = []
    in_section = False
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n\r")
                stripped = line.strip()

                # Section header — varies by powertop version
                if "Power consumers" in stripped or stripped == "Overview":
                    in_section = True
                    continue

                # A bare non-empty alphabetic line without ";" ends the section
                if in_section and stripped and ";" not in stripped:
                    if stripped[0].isalpha() and stripped not in ("Usage", "Description"):
                        in_section = False
                        continue

                if not in_section:
                    continue

                parts = [p.strip() for p in line.split(";")]

                # Skip header rows
                if not parts or parts[0].lower() in ("usage", "description", "power est.", ""):
                    continue

                # Two layouts powertop uses:
                # Standard: Usage;Wakeups/s;GPU ops/s;Disk I/O;GFX;Category;Description;PW Estimate
                # Overview:  Power est.;Usage;Name
                if len(parts) >= 8:
                    name, pw_str = parts[6], parts[7]
                elif len(parts) >= 3:
                    pw_str, name = parts[0], parts[2]
                else:
                    continue

                if not name or name in ("Description", "Name"):
                    continue

                mw = _parse_power_mw(pw_str)
                if mw is None or mw < 0.1:
                    continue

                consumers.append({"name": name, "power_mw": mw})

    except OSError:
        pass

    consumers.sort(key=lambda x: -x["power_mw"])
    return consumers[:15]


class _PowertopThread(QThread):
    done = Signal(list, list, str)  # tunables, consumers, error_msg

    def run(self):
        try:
            r = subprocess.run(
                ["pkexec", "powertop", f"--csv={_POWERTOP_CSV}", "--time=3"],
                capture_output=True, text=True, timeout=60,
            )
        except FileNotFoundError:
            self.done.emit([], [], "powertop or pkexec not found")
            return
        except subprocess.TimeoutExpired:
            self.done.emit([], [], "powertop timed out")
            return
        if r.returncode != 0:
            msg = r.stderr.strip() or "cancelled or failed"
            self.done.emit([], [], msg)
            return
        tunables  = _parse_powertop_tunables(_POWERTOP_CSV)
        consumers = _parse_powertop_consumers(_POWERTOP_CSV)
        self.done.emit(tunables, consumers, "")


class _AutoTuneThread(QThread):
    done = Signal(bool, str)

    def run(self):
        try:
            r = subprocess.run(
                ["pkexec", "powertop", "--auto-tune"],
                capture_output=True, text=True, timeout=30,
            )
        except FileNotFoundError:
            self.done.emit(False, "powertop or pkexec not found")
            return
        except subprocess.TimeoutExpired:
            self.done.emit(False, "powertop timed out")
            return
        self.done.emit(r.returncode == 0, r.stderr.strip() if r.returncode != 0 else "")


# ── CPU / process sampling ────────────────────────────────────────────────────

def _proc_cpu_snapshot() -> tuple[dict[int, tuple[str, int]], int]:
    """Return ({pid: (name, ticks)}, total_cpu_ticks)."""
    procs: dict[int, tuple[str, int]] = {}
    total = 0

    try:
        with open("/proc/stat") as f:
            line = f.readline()
        total = sum(int(x) for x in line.split()[1:])
    except (OSError, ValueError):
        pass

    for stat_path in glob.glob("/proc/*/stat"):
        try:
            with open(stat_path) as f:
                raw = f.read()
            end = raw.rfind(")")
            comm_start = raw.index("(") + 1
            comm = raw[comm_start:end]
            rest = raw[end + 2:].split()
            utime = int(rest[11])
            stime = int(rest[12])
            pid = int(raw.split("(")[0].strip())
            procs[pid] = (comm, utime + stime)
        except (OSError, ValueError, IndexError):
            pass

    return procs, total


class _CpuThread(QThread):
    """Samples /proc over ~1.2 s to get current per-process CPU %."""
    done = Signal(list)

    def run(self):
        before, total_before = _proc_cpu_snapshot()
        time.sleep(1.2)
        after, total_after = _proc_cpu_snapshot()

        delta_total = total_after - total_before
        if delta_total <= 0:
            self.done.emit([])
            return

        ncpus = os.cpu_count() or 1
        results: list[tuple[str, float, int]] = []
        for pid, (name, ticks_after) in after.items():
            if pid in before:
                delta = ticks_after - before[pid][1]
                pct = (delta / delta_total) * ncpus * 100
                if pct >= 0.2:
                    results.append((name, pct, pid))

        results.sort(key=lambda x: -x[1])
        self.done.emit(results[:12])


# ── Battery data thread ───────────────────────────────────────────────────────

class _DataThread(QThread):
    done = Signal(dict, list, list)  # info, charge_pts, rate_pts

    def __init__(self, bat: str | None, hours: float):
        super().__init__()
        self._bat   = bat
        self._hours = hours

    def run(self):
        info = _upower_info()
        charge_pts: list[tuple[int, float, str]] = []
        rate_pts:   list[tuple[int, float, str]] = []
        if self._bat:
            cf = _history_file(self._bat, "charge")
            charge_pts = _load_dat(cf, self._hours)
            rf = _history_file(self._bat, "rate")
            rate_pts = _load_dat(rf, self._hours)
            v = _sysfs(self._bat, "charge_control_end_threshold")
            if v:
                info["_sysfs_charge_limit"] = v
        self.done.emit(info, charge_pts, rate_pts)


# ── Chart helpers ─────────────────────────────────────────────────────────────

def _build_area_chart(
    bg: str,
    line_color: str,
    grad_top: QColor,
    grad_bot: QColor,
) -> tuple[QChart, QLineSeries, QAreaSeries, QDateTimeAxis, QValueAxis]:
    upper = QLineSeries()
    pen = QPen(QColor(line_color))
    pen.setWidth(2)
    upper.setPen(pen)

    area = QAreaSeries(upper)
    grad = QLinearGradient(0, 0, 0, 1)
    grad.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
    grad.setColorAt(0.0, grad_top)
    grad.setColorAt(1.0, grad_bot)
    area.setBrush(grad)
    area.setPen(QPen(Qt.NoPen))

    chart = QChart()
    chart.addSeries(area)
    chart.legend().hide()
    chart.setBackgroundBrush(QColor(bg))
    chart.setPlotAreaBackgroundVisible(False)
    chart.setMargins(QMargins(4, 4, 4, 4))

    ax_color = QColor("#707070")
    grid_color = QColor("#252525")

    x_axis = QDateTimeAxis()
    x_axis.setFormat("HH:mm")
    x_axis.setTickCount(5)
    x_axis.setLabelsColor(ax_color)
    x_axis.setGridLineColor(grid_color)
    x_axis.setLinePen(QPen(grid_color))

    y_axis = QValueAxis()
    y_axis.setTickCount(5)
    y_axis.setLabelsColor(ax_color)
    y_axis.setGridLineColor(grid_color)
    y_axis.setLinePen(QPen(grid_color))

    chart.addAxis(x_axis, Qt.AlignBottom)
    chart.addAxis(y_axis, Qt.AlignLeft)
    area.attachAxis(x_axis)
    area.attachAxis(y_axis)

    return chart, upper, area, x_axis, y_axis


def _set_time_format(axis: QDateTimeAxis, hours: float) -> None:
    if hours <= 24:
        axis.setFormat("HH:mm")
    elif hours <= 7 * 24:
        axis.setFormat("ddd HH:mm")
    else:
        axis.setFormat("MMM d")


# ── ChartView with hover tooltip ──────────────────────────────────────────────

class _ChartView(QChartView):
    def __init__(self, chart: QChart, unit: str = "%"):
        super().__init__(chart)
        self.setMouseTracking(True)
        self._unit = unit

        self._tip = QLabel(self)
        self._tip.setStyleSheet("""
            QLabel {
                background: rgba(10, 10, 10, 225);
                color: #e0e0e0;
                border: 1px solid #a7b8dd;
                border-radius: 4px;
                padding: 5px 10px;
            }
        """)
        self._tip.setVisible(False)
        self._tip.setAttribute(Qt.WA_TransparentForMouseEvents)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        chart = self.chart()
        chart_pt = chart.mapFromScene(self.mapToScene(event.pos()))
        value: QPointF = chart.mapToValue(chart_pt)

        if chart.plotArea().contains(chart_pt):
            y = value.y()
            dt = QDateTime.fromMSecsSinceEpoch(int(value.x()))
            if self._unit == "%":
                val_str = f"<b>{max(0, min(100, y)):.0f}%</b>"
            else:
                val_str = f"<b>{max(0, y):.2f} W</b>"
            self._tip.setText(f"{val_str}  {dt.toString('MMM d  HH:mm')}")
            self._tip.adjustSize()

            pos = event.pos()
            tx = pos.x() + 14
            ty = pos.y() - self._tip.height() - 10
            if tx + self._tip.width() > self.width() - 4:
                tx = pos.x() - self._tip.width() - 14
            if ty < 4:
                ty = pos.y() + 18
            self._tip.move(tx, ty)
            self._tip.setVisible(True)
        else:
            self._tip.setVisible(False)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._tip.setVisible(False)


# ── Shared bar row ────────────────────────────────────────────────────────────

def _bar_row(label: str, value_str: str, fraction: float, color: str) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(10)

    name_lbl = QLabel(label)
    name_lbl.setFixedWidth(170)
    lay.addWidget(name_lbl)

    bar = QProgressBar()
    bar.setRange(0, 1000)
    bar.setValue(int(min(max(fraction, 0.0), 1.0) * 1000))
    bar.setFixedHeight(6)
    bar.setTextVisible(False)
    bar.setStyleSheet(f"""
        QProgressBar {{
            background: #1e1e1e;
            border: none;
            border-radius: 3px;
        }}
        QProgressBar::chunk {{
            background: {color};
            border-radius: 3px;
        }}
    """)
    lay.addWidget(bar, stretch=1)

    val_lbl = QLabel(value_str)
    val_lbl.setFixedWidth(64)
    val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    val_lbl.setObjectName("fieldLabel")
    lay.addWidget(val_lbl)

    return w


# ── Tunable row ───────────────────────────────────────────────────────────────

class _TunableRow(QWidget):
    def __init__(self, desc: str, status: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)

        indicator = QLabel("●")
        indicator.setFixedWidth(14)
        indicator.setStyleSheet(
            f"color: {'#22c55e' if status == 'Good' else '#ef4444'};"
        )
        lay.addWidget(indicator)

        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        lay.addWidget(desc_lbl, stretch=1)

        status_lbl = QLabel(status)
        status_lbl.setObjectName("fieldLabel")
        status_lbl.setFixedWidth(36)
        status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(status_lbl)


# ── Main tab ──────────────────────────────────────────────────────────────────

class BatteryTab(QWidget):

    _RANGES = [
        ("Last 24 hours",  24),
        ("Last 7 days",    7 * 24),
        ("Last 30 days",  30 * 24),
    ]

    def __init__(self):
        super().__init__()
        self._bat              = _find_battery()
        self._data_thread:     _DataThread     | None = None
        self._cpu_thread:      _CpuThread      | None = None
        self._powertop_thread: _PowertopThread | None = None
        self._autotune_thread: _AutoTuneThread | None = None
        self._build_ui()
        self._load()
        self._refresh_processes()

        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._load)
        self._timer.start()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        body = QWidget()
        root = QVBoxLayout(make_centered(body))
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(14)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Battery")
        title.setObjectName("pageTitle")
        hdr.addWidget(title)
        hdr.addStretch()
        self._range_combo = QComboBox()
        for label, _ in self._RANGES:
            self._range_combo.addItem(label)
        self._range_combo.currentIndexChanged.connect(self._load)
        hdr.addWidget(self._range_combo)
        root.addLayout(hdr)

        self._status_lbl = QLabel()
        self._status_lbl.setObjectName("statusLabel")
        root.addWidget(self._status_lbl)

        # ── Charge % chart ────────────────────────────────────────────────────
        charge_title = QLabel("Charge")
        charge_title.setObjectName("sectionTitle")
        root.addWidget(charge_title)

        (self._charge_chart,
         self._charge_upper,
         self._charge_area,
         self._charge_x,
         self._charge_y) = _build_area_chart(
            "#101010", "#a7b8dd",
            QColor(167, 184, 221, 80), QColor(167, 184, 221, 5),
        )
        self._charge_y.setRange(0, 100)
        self._charge_y.setLabelFormat("%d%%")

        charge_view = _ChartView(self._charge_chart, unit="%")
        charge_view.setRenderHint(QPainter.Antialiasing)
        charge_view.setMinimumHeight(190)
        root.addWidget(charge_view)

        # ── Power draw (W) chart ──────────────────────────────────────────────
        rate_title = QLabel("Power draw")
        rate_title.setObjectName("sectionTitle")
        root.addWidget(rate_title)

        (self._rate_chart,
         self._rate_upper,
         self._rate_area,
         self._rate_x,
         self._rate_y) = _build_area_chart(
            "#101010", "#f59e0b",
            QColor(245, 158, 11, 70), QColor(245, 158, 11, 5),
        )
        self._rate_y.setLabelFormat("%.1f W")
        self._rate_y.setRange(0, 20)

        self._rate_view = _ChartView(self._rate_chart, unit="W")
        self._rate_view.setRenderHint(QPainter.Antialiasing)
        self._rate_view.setMinimumHeight(160)

        self._rate_empty = QLabel("No power draw history available")
        self._rate_empty.setObjectName("statusLabel")
        self._rate_empty.setAlignment(Qt.AlignCenter)
        self._rate_empty.setVisible(False)

        root.addWidget(self._rate_view)
        root.addWidget(self._rate_empty)

        root.addWidget(separator())

        # ── Stats grid ────────────────────────────────────────────────────────
        grid = QGridLayout()
        grid.setHorizontalSpacing(32)
        grid.setVerticalSpacing(16)

        self._stat_lbls: dict[str, QLabel] = {}
        _stat_defs = [
            ("percentage",    "Charge"),
            ("state",         "Status"),
            ("energy-rate",   "Power draw"),
            ("time to empty", "Time remaining"),
            ("charge-cycles", "Cycles"),
            ("capacity",      "Health"),
            ("voltage",       "Voltage"),
            ("technology",    "Technology"),
        ]
        for i, (key, label) in enumerate(_stat_defs):
            row, col = divmod(i, 2)
            cell = QWidget()
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(2)
            field_lbl = QLabel(label)
            field_lbl.setObjectName("fieldLabel")
            val_lbl = QLabel("—")
            val_lbl.setObjectName("detailTitle")
            cl.addWidget(field_lbl)
            cl.addWidget(val_lbl)
            grid.addWidget(cell, row, col)
            self._stat_lbls[key] = val_lbl

        root.addLayout(grid)

        self._limit_row = QWidget()
        ll = QHBoxLayout(self._limit_row)
        ll.setContentsMargins(0, 4, 0, 0)
        ll.setSpacing(12)
        limit_lbl = QLabel("Charge limit")
        limit_lbl.setObjectName("fieldLabel")
        self._limit_val = QLabel("—")
        self._limit_val.setObjectName("detailTitle")
        ll.addWidget(limit_lbl)
        ll.addWidget(self._limit_val)
        ll.addStretch()
        self._limit_row.setVisible(False)
        root.addWidget(self._limit_row)

        root.addWidget(separator())

        # ── Power by process (powertop) ───────────────────────────────────────
        pw_hdr = QHBoxLayout()
        pw_title = QLabel("Power by process")
        pw_title.setObjectName("sectionTitle")
        pw_hdr.addWidget(pw_title)
        pw_hdr.addStretch()
        self._pw_status = QLabel()
        self._pw_status.setObjectName("statusLabel")
        pw_hdr.addWidget(self._pw_status)
        self._scan_btn = QPushButton("Scan")
        self._scan_btn.clicked.connect(self._scan_powertop)
        pw_hdr.addWidget(self._scan_btn)
        self._autotune_btn = QPushButton("Apply all savings")
        self._autotune_btn.setEnabled(False)
        self._autotune_btn.clicked.connect(self._auto_tune)
        pw_hdr.addWidget(self._autotune_btn)
        root.addLayout(pw_hdr)

        pw_note = QLabel(
            "Requires administrator rights (polkit). Scan takes ~3 s using powertop."
        )
        pw_note.setObjectName("statusLabel")
        pw_note.setWordWrap(True)
        root.addWidget(pw_note)

        self._pw_container = QVBoxLayout()
        self._pw_container.setSpacing(2)
        root.addLayout(self._pw_container)

        root.addWidget(separator())

        # ── CPU activity ──────────────────────────────────────────────────────
        cpu_hdr = QHBoxLayout()
        cpu_title = QLabel("CPU activity")
        cpu_title.setObjectName("sectionTitle")
        cpu_hdr.addWidget(cpu_title)
        cpu_hdr.addStretch()
        self._proc_status = QLabel()
        self._proc_status.setObjectName("statusLabel")
        cpu_hdr.addWidget(self._proc_status)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._refresh_processes)
        cpu_hdr.addWidget(self._refresh_btn)
        root.addLayout(cpu_hdr)

        self._proc_container = QVBoxLayout()
        self._proc_container.setSpacing(2)
        root.addLayout(self._proc_container)

        root.addWidget(separator())

        # ── Power tunables ────────────────────────────────────────────────────
        tune_hdr = QHBoxLayout()
        tune_title = QLabel("Power Tunables")
        tune_title.setObjectName("sectionTitle")
        tune_hdr.addWidget(tune_title)
        tune_hdr.addStretch()
        self._tune_status = QLabel()
        self._tune_status.setObjectName("statusLabel")
        tune_hdr.addWidget(self._tune_status)
        root.addLayout(tune_hdr)

        tune_note = QLabel("Populated automatically when you Scan above.")
        tune_note.setObjectName("statusLabel")
        tune_note.setWordWrap(True)
        root.addWidget(tune_note)

        self._tune_container = QVBoxLayout()
        self._tune_container.setSpacing(1)
        root.addLayout(self._tune_container)

        root.addStretch()
        scroll.setWidget(body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Battery data ──────────────────────────────────────────────────────────

    def _current_hours(self) -> float:
        return self._RANGES[self._range_combo.currentIndex()][1]

    def _load(self):
        if self._data_thread and self._data_thread.isRunning():
            return
        self._status_lbl.setText("Loading…")
        self._data_thread = _DataThread(self._bat, self._current_hours())
        self._data_thread.done.connect(self._on_data_done)
        self._data_thread.start()

    def _on_data_done(self, info: dict, charge_pts: list, rate_pts: list):
        self._status_lbl.setText("")
        self._update_stats(info)
        self._update_charge_chart(charge_pts)
        self._update_rate_chart(rate_pts)

    def _update_stats(self, info: dict):
        state = info.get("state", "").lower()
        time_key = "time to full" if "charging" in state else "time to empty"
        for key, lbl in self._stat_lbls.items():
            lbl.setText(info.get(time_key if key == "time to empty" else key, "—"))
        limit = info.get("_sysfs_charge_limit", "")
        if limit:
            self._limit_val.setText(f"{limit}%")
            self._limit_row.setVisible(True)

    def _update_charge_chart(self, pts: list):
        self._charge_upper.clear()
        if not pts:
            self._status_lbl.setText("No history data available")
            return
        for ts_ms, val, _ in pts:
            self._charge_upper.append(ts_ms, val)
        min_ts = min(p[0] for p in pts)
        max_ts = max(p[0] for p in pts)
        self._charge_x.setRange(
            QDateTime.fromMSecsSinceEpoch(int(min_ts)),
            QDateTime.fromMSecsSinceEpoch(int(max_ts)),
        )
        _set_time_format(self._charge_x, self._current_hours())

    def _update_rate_chart(self, pts: list):
        self._rate_upper.clear()

        # Only show discharge periods — charging rate would inflate the scale
        discharge_pts = [(ts, val, s) for ts, val, s in pts if "discharge" in s.lower()]
        if not discharge_pts:
            self._rate_view.setVisible(False)
            self._rate_empty.setVisible(True)
            return

        self._rate_view.setVisible(True)
        self._rate_empty.setVisible(False)

        for ts_ms, val, _ in discharge_pts:
            self._rate_upper.append(ts_ms, val)

        min_ts = min(p[0] for p in discharge_pts)
        max_ts = max(p[0] for p in discharge_pts)
        self._rate_x.setRange(
            QDateTime.fromMSecsSinceEpoch(int(min_ts)),
            QDateTime.fromMSecsSinceEpoch(int(max_ts)),
        )
        _set_time_format(self._rate_x, self._current_hours())

        max_w = max(p[1] for p in discharge_pts)
        self._rate_y.setRange(0, max(max_w * 1.15, 5.0))

    # ── CPU sampling ──────────────────────────────────────────────────────────

    def _refresh_processes(self):
        if self._cpu_thread and self._cpu_thread.isRunning():
            return
        self._refresh_btn.setEnabled(False)
        self._proc_status.setText("Sampling…")
        self._cpu_thread = _CpuThread()
        self._cpu_thread.done.connect(self._on_cpu_done)
        self._cpu_thread.start()

    def _on_cpu_done(self, results: list):
        self._refresh_btn.setEnabled(True)
        self._proc_status.setText("")
        _clear_layout(self._proc_container)

        if not results:
            lbl = QLabel("No data")
            lbl.setObjectName("statusLabel")
            self._proc_container.addWidget(lbl)
            return

        max_pct = max(r[1] for r in results)
        for name, pct, _ in results:
            self._proc_container.addWidget(
                _bar_row(name, f"{pct:.1f}%", pct / max(max_pct, 1), "#a7b8dd")
            )

    # ── Powertop scan ─────────────────────────────────────────────────────────

    def _scan_powertop(self):
        if self._powertop_thread and self._powertop_thread.isRunning():
            return
        self._scan_btn.setEnabled(False)
        self._autotune_btn.setEnabled(False)
        self._pw_status.setText("Scanning… (polkit prompt may appear)")
        self._powertop_thread = _PowertopThread()
        self._powertop_thread.done.connect(self._on_powertop_done)
        self._powertop_thread.start()

    def _on_powertop_done(self, tunables: list, consumers: list, error: str):
        self._scan_btn.setEnabled(True)
        _clear_layout(self._pw_container)
        _clear_layout(self._tune_container)

        if error:
            self._pw_status.setText(f"Error: {error}")
            self._tune_status.setText("")
            return

        # ── Power by process ──────────────────────────────────────────────────
        if consumers:
            max_mw = max(c["power_mw"] for c in consumers)
            for c in consumers:
                mw = c["power_mw"]
                label = f"{mw/1000:.2f} W" if mw >= 1000 else f"{mw:.0f} mW"
                self._pw_container.addWidget(
                    _bar_row(c["name"], label, mw / max(max_mw, 1), "#f59e0b")
                )
            self._pw_status.setText(f"{len(consumers)} processes")
        else:
            lbl = QLabel("No per-process power data in powertop output")
            lbl.setObjectName("statusLabel")
            self._pw_container.addWidget(lbl)
            self._pw_status.setText("")

        # ── Tunables ──────────────────────────────────────────────────────────
        bad  = sum(1 for t in tunables if t["status"] == "Bad")
        good = len(tunables) - bad
        self._tune_status.setText(f"{good} good · {bad} need attention")
        self._autotune_btn.setEnabled(bad > 0)

        if not tunables:
            lbl = QLabel("No tunables found in powertop output")
            lbl.setObjectName("statusLabel")
            self._tune_container.addWidget(lbl)
            return

        for t in sorted(tunables, key=lambda x: x["status"] != "Bad"):
            self._tune_container.addWidget(_TunableRow(t["desc"], t["status"]))

    def _auto_tune(self):
        if self._autotune_thread and self._autotune_thread.isRunning():
            return
        self._autotune_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._tune_status.setText("Applying savings… (polkit prompt may appear)")
        self._autotune_thread = _AutoTuneThread()
        self._autotune_thread.done.connect(self._on_autotune_done)
        self._autotune_thread.start()

    def _on_autotune_done(self, ok: bool, error: str):
        if ok:
            self._pw_status.setText("Applied — re-scanning…")
            self._scan_powertop()
        else:
            self._scan_btn.setEnabled(True)
            self._autotune_btn.setEnabled(True)
            self._tune_status.setText(f"Failed: {error or 'unknown error'}")


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
