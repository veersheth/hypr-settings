"""Battery status and history page."""
import glob
import os
import re
import subprocess
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

_BAT_SYS   = "/sys/class/power_supply"
_UPOWER_DB = "/var/lib/upower"


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
    # Skip Bluetooth devices (MAC address pattern xx:xx in filename)
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


# ── CPU / process sampling ────────────────────────────────────────────────────

def _proc_cpu_snapshot() -> tuple[dict[int, tuple[str, int]], int]:
    """Return ({pid: (name, ticks)}, total_cpu_ticks)."""
    procs: dict[int, tuple[str, int]] = {}
    total = 0

    try:
        with open("/proc/stat") as f:
            line = f.readline()        # first line is "cpu ..."
        total = sum(int(x) for x in line.split()[1:])
    except (OSError, ValueError):
        pass

    for stat_path in glob.glob("/proc/*/stat"):
        try:
            with open(stat_path) as f:
                raw = f.read()
            # comm is between first '(' and last ')' — can contain spaces/parens
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
    done = Signal(list)   # list of (name, cpu_pct, pid)

    def run(self):
        before, total_before = _proc_cpu_snapshot()
        time.sleep(1.2)
        after, total_after = _proc_cpu_snapshot()

        delta_total = total_after - total_before
        if delta_total <= 0:
            self.done.emit([])
            return

        try:
            ncpus = os.cpu_count() or 1
        except Exception:
            ncpus = 1

        results: list[tuple[str, float, int]] = []
        for pid, (name, ticks_after) in after.items():
            if pid in before:
                delta = ticks_after - before[pid][1]
                # multiply by ncpus so 100% = one full core saturated
                pct = (delta / delta_total) * ncpus * 100
                if pct >= 0.2:
                    results.append((name, pct, pid))

        results.sort(key=lambda x: -x[1])
        self.done.emit(results[:12])


# ── Battery data thread ───────────────────────────────────────────────────────

class _DataThread(QThread):
    done = Signal(dict, list)

    def __init__(self, bat: str | None, hours: float):
        super().__init__()
        self._bat   = bat
        self._hours = hours

    def run(self):
        info = _upower_info()
        pts: list[tuple[int, float, str]] = []
        if self._bat:
            cf = _history_file(self._bat, "charge")
            pts = _load_dat(cf, self._hours)
            v = _sysfs(self._bat, "charge_control_end_threshold")
            if v:
                info["_sysfs_charge_limit"] = v
        self.done.emit(info, pts)


# ── Custom chart view with hover tooltip ──────────────────────────────────────

class _ChartView(QChartView):
    def __init__(self, chart: QChart):
        super().__init__(chart)
        self.setMouseTracking(True)

        self._tip = QLabel(self)
        self._tip.setStyleSheet("""
            QLabel {
                background: rgba(10, 10, 10, 225);
                color: #e0e0e0;
                border: 1px solid #3b82f6;
                border-radius: 4px;
                padding: 5px 10px;
            }
        """)
        self._tip.setVisible(False)
        self._tip.setAttribute(Qt.WA_TransparentForMouseEvents)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        chart = self.chart()
        scene_pt = self.mapToScene(event.pos())
        chart_pt = chart.mapFromScene(scene_pt)
        value: QPointF = chart.mapToValue(chart_pt)

        ts_ms = value.x()
        pct   = value.y()

        if chart.plotArea().contains(chart_pt) and -5 <= pct <= 105:
            dt = QDateTime.fromMSecsSinceEpoch(int(ts_ms))
            self._tip.setText(f"<b>{max(0, min(100, pct)):.0f}%</b>  {dt.toString('MMM d  HH:mm')}")
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


# ── Process row widget ────────────────────────────────────────────────────────

class _ProcRow(QWidget):
    def __init__(self, name: str, pct: float):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)

        name_lbl = QLabel(name)
        name_lbl.setFixedWidth(160)
        lay.addWidget(name_lbl)

        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(int(min(pct, 100) * 10))
        bar.setFixedHeight(6)
        bar.setTextVisible(False)
        bar.setStyleSheet("""
            QProgressBar {
                background: #1e1e1e;
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: #3b82f6;
                border-radius: 3px;
            }
        """)
        lay.addWidget(bar, stretch=1)

        pct_lbl = QLabel(f"{pct:.1f}%")
        pct_lbl.setFixedWidth(46)
        pct_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pct_lbl.setObjectName("fieldLabel")
        lay.addWidget(pct_lbl)


# ── Main tab ──────────────────────────────────────────────────────────────────

class BatteryTab(QWidget):

    _RANGES = [
        ("Last 24 hours",  24),
        ("Last 7 days",    7 * 24),
        ("Last 30 days",  30 * 24),
    ]

    def __init__(self):
        super().__init__()
        self._bat         = _find_battery()
        self._data_thread: _DataThread | None = None
        self._cpu_thread:  _CpuThread  | None = None
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

        # ── Chart ─────────────────────────────────────────────────────────────
        self._upper = QLineSeries()
        pen = QPen(QColor("#3b82f6"))
        pen.setWidth(2)
        self._upper.setPen(pen)

        self._area = QAreaSeries(self._upper)
        grad = QLinearGradient(0, 0, 0, 1)
        grad.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
        grad.setColorAt(0.0, QColor(59, 130, 246, 80))
        grad.setColorAt(1.0, QColor(59, 130, 246, 5))
        self._area.setBrush(grad)
        self._area.setPen(QPen(Qt.NoPen))

        chart = QChart()
        chart.addSeries(self._area)
        chart.legend().hide()
        chart.setBackgroundBrush(QColor("#111111"))
        chart.setPlotAreaBackgroundVisible(False)
        chart.setMargins(QMargins(4, 4, 4, 4))
        self._chart = chart

        _ax_lbl = QColor("#707070")
        _grid   = QColor("#252525")

        self._x_axis = QDateTimeAxis()
        self._x_axis.setFormat("HH:mm")
        self._x_axis.setTickCount(5)
        self._x_axis.setLabelsColor(_ax_lbl)
        self._x_axis.setGridLineColor(_grid)
        self._x_axis.setLinePen(QPen(_grid))

        self._y_axis = QValueAxis()
        self._y_axis.setRange(0, 100)
        self._y_axis.setLabelFormat("%d%%")
        self._y_axis.setTickCount(6)
        self._y_axis.setLabelsColor(_ax_lbl)
        self._y_axis.setGridLineColor(_grid)
        self._y_axis.setLinePen(QPen(_grid))

        chart.addAxis(self._x_axis, Qt.AlignBottom)
        chart.addAxis(self._y_axis, Qt.AlignLeft)
        self._area.attachAxis(self._x_axis)
        self._area.attachAxis(self._y_axis)

        chart_view = _ChartView(chart)
        chart_view.setRenderHint(QPainter.Antialiasing)
        chart_view.setMinimumHeight(220)
        root.addWidget(chart_view)

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

        # Charge limit (Framework / supported devices)
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

        # ── Top processes ─────────────────────────────────────────────────────
        proc_hdr = QHBoxLayout()
        sec_lbl = QLabel("Top processes by CPU")
        sec_lbl.setObjectName("sectionTitle")
        proc_hdr.addWidget(sec_lbl)
        proc_hdr.addStretch()
        self._proc_status = QLabel()
        self._proc_status.setObjectName("statusLabel")
        proc_hdr.addWidget(self._proc_status)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._refresh_processes)
        proc_hdr.addWidget(self._refresh_btn)
        root.addLayout(proc_hdr)

        note = QLabel("CPU usage is the primary driver of battery drain.")
        note.setObjectName("statusLabel")
        root.addWidget(note)

        self._proc_container = QVBoxLayout()
        self._proc_container.setSpacing(2)
        root.addLayout(self._proc_container)

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

    def _on_data_done(self, info: dict, pts: list):
        self._status_lbl.setText("")
        self._update_stats(info)
        self._update_chart(pts)

    def _update_stats(self, info: dict):
        state = info.get("state", "").lower()
        time_key = "time to full" if "charging" in state else "time to empty"
        for key, lbl in self._stat_lbls.items():
            if key == "time to empty":
                lbl.setText(info.get(time_key, "—"))
            else:
                lbl.setText(info.get(key, "—"))
        limit = info.get("_sysfs_charge_limit", "")
        if limit:
            self._limit_val.setText(f"{limit}%")
            self._limit_row.setVisible(True)

    def _update_chart(self, pts: list):
        self._upper.clear()
        if not pts:
            self._status_lbl.setText("No history data available")
            return
        for ts_ms, val, _ in pts:
            self._upper.append(ts_ms, val)
        min_ts = min(p[0] for p in pts)
        max_ts = max(p[0] for p in pts)
        self._x_axis.setRange(
            QDateTime.fromMSecsSinceEpoch(int(min_ts)),
            QDateTime.fromMSecsSinceEpoch(int(max_ts)),
        )
        hours = self._current_hours()
        if hours <= 24:
            self._x_axis.setFormat("HH:mm")
        elif hours <= 7 * 24:
            self._x_axis.setFormat("ddd HH:mm")
        else:
            self._x_axis.setFormat("MMM d")

    # ── Process sampling ──────────────────────────────────────────────────────

    def _refresh_processes(self):
        if self._cpu_thread and self._cpu_thread.isRunning():
            return
        self._refresh_btn.setEnabled(False)
        self._proc_status.setText("Sampling for 1.2 s…")
        self._cpu_thread = _CpuThread()
        self._cpu_thread.done.connect(self._on_cpu_done)
        self._cpu_thread.start()

    def _on_cpu_done(self, results: list):
        self._refresh_btn.setEnabled(True)
        self._proc_status.setText("")

        # Clear old rows
        while self._proc_container.count():
            item = self._proc_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not results:
            lbl = QLabel("No data")
            lbl.setObjectName("statusLabel")
            self._proc_container.addWidget(lbl)
            return

        for name, pct, _ in results:
            self._proc_container.addWidget(_ProcRow(name, pct))
