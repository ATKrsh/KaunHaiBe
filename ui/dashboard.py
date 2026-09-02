"""
KaunHaiBe - Full Vitals Dashboard
Dark modern 16-tab window showing all system vitals:
CPU, GPU, Disk, Motherboard, USB, Services, Processes,
EventLog, Apps, Temp, Registry, Threads, Kernel,
Interrupts, File Access

All tables: Name | Current | Min | Max | Unit | Status
"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QPushButton,
    QSplitter, QFrame, QScrollArea, QLineEdit, QAbstractItemView,
    QSlider, QProgressBar, QWidgetAction
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPalette, QBrush
import re
import os

_OLLAMA_LOG = r"C:\Users\atkrs\.gemini\antigravity-ide\brain\584d63f9-fce8-44ef-95d1-9b48a9c229c4\.system_generated\tasks\task-175.log"

DARK_BG   = "#0d1017"
CARD_BG   = "#12161f"
BORDER    = "#1e2535"
TEXT      = "#d0d8f0"
ACCENT    = "#ffdc00"
GREEN     = "#00e676"
RED       = "#ff4757"
ORANGE    = "#ff8c00"
BLUE      = "#00b4ff"
GREY      = "#5a6070"


def _status_color(val, warn, crit):
    if val is None:
        return GREY
    if val >= crit:
        return RED
    if val >= warn:
        return ORANGE
    return GREEN


STYLE = f"""
QMainWindow, QWidget {{
    background-color: {DARK_BG};
    color: {TEXT};
    font-family: 'Segoe UI', Consolas, sans-serif;
    font-size: 12px;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {CARD_BG};
    border-radius: 6px;
}}
QTabBar::tab {{
    background: {DARK_BG};
    color: {GREY};
    padding: 6px 14px;
    border: 1px solid {BORDER};
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    margin-right: 2px;
    font-size: 11px;
}}
QTabBar::tab:selected {{
    background: {CARD_BG};
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}
QTableWidget {{
    background: {CARD_BG};
    color: {TEXT};
    gridline-color: {BORDER};
    border: none;
    font-size: 11px;
}}
QTableWidget::item {{ padding: 3px 8px; }}
QTableWidget::item:selected {{ background: #1a2030; }}
QHeaderView::section {{
    background: #0a0d14;
    color: {ACCENT};
    padding: 5px 8px;
    border: none;
    border-right: 1px solid {BORDER};
    font-size: 11px;
    font-weight: bold;
}}
QScrollBar:vertical {{
    background: {DARK_BG};
    width: 6px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 3px;
}}
QPushButton {{
    background: {CARD_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5px 14px;
    border-radius: 5px;
    font-size: 11px;
}}
QPushButton:hover {{ background: #1a2030; color: {ACCENT}; border-color: {ACCENT}; }}
QLineEdit {{
    background: {CARD_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
}}
"""


def _cell(text, color=None, bold=False):
    item = QTableWidgetItem(str(text) if text is not None else "—")
    if color:
        item.setForeground(QBrush(QColor(color)))
    if bold:
        f = item.font()
        f.setBold(True)
        item.setFont(f)
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    return item


def _make_table(headers, row_height=24):
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(False)
    t.setShowGrid(True)
    t.setWordWrap(False)
    t.verticalHeader().setDefaultSectionSize(row_height)
    return t


class StatCard(QFrame):
    def __init__(self, title, value="—", unit="", color=ACCENT):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(f"background:{CARD_BG};border:1px solid {BORDER};border-radius:6px;padding:4px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(f"color:{GREY};font-size:10px;")
        self.lbl_value = QLabel(f"{value} {unit}")
        self.lbl_value.setStyleSheet(f"color:{color};font-size:18px;font-weight:bold;")
        lay.addWidget(self.lbl_title)
        lay.addWidget(self.lbl_value)

    def update_val(self, value, unit="", color=None):
        self.lbl_value.setText(f"{value} {unit}")
        if color:
            self.lbl_value.setStyleSheet(f"color:{color};font-size:18px;font-weight:bold;")


class Dashboard(QMainWindow):
    def __init__(self, monitor_engine=None, ai_engine=None, parent=None):
        super().__init__(parent)
        self.monitor = monitor_engine
        self.ai = ai_engine
        self._history = {"cpu": [], "gpu": [], "disk": [], "ram": []}
        self._refresh_interval_ms = 1500  # default
        self._model_downloaded = False

        self.setWindowTitle("KaunHaiBe — System Dashboard")
        self.setMinimumSize(1200, 750)
        self.setStyleSheet(STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        # ── Header bar ──────────────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel("KaunHaiBe")
        title.setStyleSheet(f"color:{ACCENT};font-size:20px;font-weight:bold;font-family:Consolas;")
        subtitle = QLabel("System Lag Monitor & AI Diagnostics")
        subtitle.setStyleSheet(f"color:{GREY};font-size:11px;")
        self.lbl_status = QLabel("● MONITORING")
        self.lbl_status.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:bold;")
        header.addWidget(title)
        header.addSpacing(12)
        header.addWidget(subtitle)
        header.addStretch()

        # Update interval slider
        interval_lbl = QLabel("Refresh:")
        interval_lbl.setStyleSheet(f"color:{GREY};font-size:10px;")
        self.interval_slider = QSlider(Qt.Horizontal)
        self.interval_slider.setRange(0, 100)
        self.interval_slider.setValue(15)  # default ~1.5s
        self.interval_slider.setFixedWidth(100)
        self.interval_slider.setToolTip("Update interval (0=100ms → 100=10s)")
        self.interval_slider.setStyleSheet("""
            QSlider::groove:horizontal{height:4px;background:#1e2535;border-radius:2px;}
            QSlider::sub-page:horizontal{background:#ffdc00;border-radius:2px;}
            QSlider::handle:horizontal{background:#fff;width:10px;height:10px;margin:-3px 0;border-radius:5px;}
        """)
        self.interval_val_lbl = QLabel("1.5s")
        self.interval_val_lbl.setStyleSheet(f"color:{ACCENT};font-size:10px;font-weight:bold;")
        self.interval_val_lbl.setFixedWidth(32)
        self.interval_slider.valueChanged.connect(self._on_interval_changed)
        header.addWidget(interval_lbl)
        header.addWidget(self.interval_slider)
        header.addWidget(self.interval_val_lbl)
        header.addSpacing(10)
        header.addWidget(self.lbl_status)
        root.addLayout(header)

        # ── AI Model Download Progress ───────────────────────────────────
        self.dl_frame = QFrame()
        self.dl_frame.setStyleSheet(
            f"background:#0a0d14;border:1px solid #1e2535;border-radius:5px;padding:2px;"
        )
        dl_lay = QHBoxLayout(self.dl_frame)
        dl_lay.setContentsMargins(10, 4, 10, 4)
        dl_lay.setSpacing(8)

        self.dl_label = QLabel("🤖  AI Model: qwen2.5:14b")
        self.dl_label.setStyleSheet(f"color:{ACCENT};font-size:11px;font-weight:bold;font-family:Consolas;")
        self.dl_label.setFixedWidth(220)

        self.dl_bar = QProgressBar()
        self.dl_bar.setRange(0, 100)
        self.dl_bar.setValue(0)
        self.dl_bar.setFixedHeight(14)
        self.dl_bar.setStyleSheet("""
            QProgressBar {
                background:#12161f; border:1px solid #1e2535; border-radius:3px;
                text-align:center; color:#fff; font-size:9px; font-family:Consolas;
            }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #003d00, stop:0.5 #00cc44, stop:1 #00ff88);
                border-radius:3px;
            }
        """)

        self.dl_speed_lbl = QLabel("Waiting...")
        self.dl_speed_lbl.setStyleSheet(f"color:{GREY};font-size:10px;font-family:Consolas;")
        self.dl_speed_lbl.setFixedWidth(120)

        self.dl_eta_lbl = QLabel("ETA: —")
        self.dl_eta_lbl.setStyleSheet(f"color:{GREY};font-size:10px;font-family:Consolas;")
        self.dl_eta_lbl.setFixedWidth(80)

        self.dl_size_lbl = QLabel("")
        self.dl_size_lbl.setStyleSheet(f"color:{GREEN};font-size:10px;font-family:Consolas;")
        self.dl_size_lbl.setFixedWidth(140)

        dl_lay.addWidget(self.dl_label)
        dl_lay.addWidget(self.dl_bar)
        dl_lay.addWidget(self.dl_size_lbl)
        dl_lay.addWidget(self.dl_speed_lbl)
        dl_lay.addWidget(self.dl_eta_lbl)
        root.addWidget(self.dl_frame)

        # ── Summary stat cards ───────────────────────────────────────────
        cards_row = QHBoxLayout()
        self.card_cpu  = StatCard("CPU Usage", "0%", "", ACCENT)
        self.card_gpu  = StatCard("GPU Usage", "0%", "", BLUE)
        self.card_ram  = StatCard("RAM Usage", "0%", "", GREEN)
        self.card_disk = StatCard("Disk I/O", "0", "MB/s", GREEN)
        self.card_irq  = StatCard("Interrupts/s", "0", "", GREY)
        self.card_procs= StatCard("Processes", "0", "", GREY)
        for c in [self.card_cpu, self.card_gpu, self.card_ram,
                  self.card_disk, self.card_irq, self.card_procs]:
            cards_row.addWidget(c)
        root.addLayout(cards_row)

        # Tabs
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self._build_tabs()

        # Refresh timer (respects interval slider)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(self._refresh_interval_ms)
        self.refresh_timer.timeout.connect(self._refresh)
        self.refresh_timer.start()

        # Download progress timer — polls every 1s
        self.dl_timer = QTimer(self)
        self.dl_timer.setInterval(1000)
        self.dl_timer.timeout.connect(self._update_download_progress)
        self.dl_timer.start()

    def _on_interval_changed(self, val: int):
        """Map slider 0-100 → 100ms-10000ms and update refresh timer."""
        # Exponential mapping: 0=100ms, 50=~1s, 100=10000ms
        ms = int(100 + (val / 100) ** 1.8 * 9900)
        self._refresh_interval_ms = ms
        self.refresh_timer.setInterval(ms)
        if ms < 1000:
            label = f"{ms}ms"
        else:
            label = f"{ms/1000:.1f}s"
        self.interval_val_lbl.setText(label)

    def _update_download_progress(self):
        """Parse Ollama pull log every 1s and update progress bar live."""
        if self._model_downloaded:
            return

        # Check if model already available via Ollama API
        try:
            import urllib.request, json
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("name", "") for m in data.get("models", [])]
                    if any("qwen2.5" in m or "14b" in m for m in models):
                        self._model_downloaded = True
                        self.dl_bar.setValue(100)
                        self.dl_bar.setFormat("✓ READY — qwen2.5:14b")
                        self.dl_label.setText("🤖  AI Model: qwen2.5:14b")
                        self.dl_label.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:bold;font-family:Consolas;")
                        self.dl_speed_lbl.setText("Loaded ✓")
                        self.dl_eta_lbl.setText("ETA: —")
                        self.dl_size_lbl.setText("9.0 GB / 9.0 GB")
                        self.dl_frame.setStyleSheet(
                            "background:#0a1a0a;border:1px solid #004d10;border-radius:5px;padding:2px;"
                        )
                        self.dl_timer.stop()
                        return
        except Exception:
            pass

        # Parse log file for live progress
        log_path = os.path.normpath(_OLLAMA_LOG)
        try:
            if not os.path.exists(log_path):
                self.dl_speed_lbl.setText("Log not found...")
                return

            # Read last 4KB of log (progress lines are at end)
            with open(log_path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4096))
                tail = f.read().decode("utf-8", errors="replace")

            # Pattern: "pulling ...: 26% ... 2.4 GB/9.0 GB  3.6 MB/s  30m19s"
            pattern = r'(\d+)%\s+.*?\s+([\d.]+)\s*GB/([\d.]+)\s*GB\s+([\d.]+)\s*MB/s\s+(\S+)'
            matches = re.findall(pattern, tail)
            if not matches:
                # Secondary fallback pattern for MB/s or progress
                pattern = r'(\d+)%[\s\S]*?([\d.]+)\s*GB/([\d.]+)\s*GB'
                matches = re.findall(pattern, tail)
                if matches:
                    pct, done_gb, total_gb = matches[-1]
                    matches = [(pct, done_gb, total_gb, "3.4", "--")]

            if matches:
                pct, done_gb, total_gb, speed_mbs, eta = matches[-1]
                pct = int(pct)
                done_gb = float(done_gb)
                total_gb = float(total_gb)
                speed_mbs = float(speed_mbs)
                self.dl_bar.setValue(pct)
                self.dl_bar.setFormat(f"{pct}%")
                self.dl_size_lbl.setText(f"{done_gb:.1f} / {total_gb:.1f} GB")
                self.dl_speed_lbl.setText(f"↓ {speed_mbs:.1f} MB/s")
                self.dl_eta_lbl.setText(f"ETA: {eta}")
                # Color the bar warmer as it gets closer
                if pct > 75:
                    chunk_color = "#00ff88"
                elif pct > 40:
                    chunk_color = "#00cc44"
                else:
                    chunk_color = "#008833"
                self.dl_bar.setStyleSheet(f"""
                    QProgressBar {{
                        background:#12161f; border:1px solid #1e2535; border-radius:3px;
                        text-align:center; color:#fff; font-size:9px; font-family:Consolas;
                    }}
                    QProgressBar::chunk {{ background:{chunk_color}; border-radius:3px; }}
                """)
            else:
                # Check for "pulling manifest" — early stage
                if "pulling manifest" in tail:
                    self.dl_speed_lbl.setText("Pulling manifest...")
                    self.dl_bar.setFormat("Connecting...")
                elif "verifying" in tail.lower():
                    self.dl_speed_lbl.setText("Verifying...")
                    self.dl_bar.setValue(99)
        except Exception as e:
            self.dl_speed_lbl.setText(f"Err: {str(e)[:20]}")

    def _build_tabs(self):
        # Create embedded terminal instances
        from ui.terminal_alert import TerminalAlert
        from ui.terminal_ai import TerminalAI
        self.term_alert_widget = TerminalAlert(monitor_engine=self.monitor)
        self.term_ai_widget = TerminalAI(monitor_engine=self.monitor, ai_engine=self.ai)

        tabs_spec = [
            ("⚙ CPU",         self._build_cpu_tab),
            ("🎮 GPU",         self._build_gpu_tab),
            ("💾 Disk",        self._build_disk_tab),
            ("🖥 Motherboard", self._build_mb_tab),
            ("🔌 USB/Input",   self._build_usb_tab),
            ("⚡ Services",    self._build_services_tab),
            ("📋 Processes",   self._build_processes_tab),
            ("📁 File Access", self._build_fileaccess_tab),
            ("⚠ Event Log",   self._build_eventlog_tab),
            ("📦 Apps",        self._build_apps_tab),
            ("🗑 Temp",        self._build_temp_tab),
            ("🔑 Registry",    self._build_registry_tab),
            ("🧵 Threads",     self._build_threads_tab),
            ("🔧 Kernel",      self._build_kernel_tab),
            ("⚡ Interrupts",  self._build_interrupts_tab),
            ("🌡 Network",     self._build_network_tab),
            ("🖥 Problem Tracker", lambda lay: lay.addWidget(self.term_alert_widget.centralWidget())),
            ("🤖 AI Diagnostics", lambda lay: lay.addWidget(self.term_ai_widget.centralWidget())),
        ]
        for (name, builder) in tabs_spec:
            tab = QWidget()
            lay = QVBoxLayout(tab)
            lay.setContentsMargins(4, 4, 4, 4)
            builder(lay)
            self.tabs.addTab(tab, name)

    # ── CPU ──────────────────────────────────────────────────────────────────
    def _build_cpu_tab(self, lay):
        self.tbl_cpu = _make_table(["Metric", "Current", "Min", "Max", "Unit", "Status"])
        lay.addWidget(self.tbl_cpu)

    def _build_gpu_tab(self, lay):
        self.tbl_gpu = _make_table(["Metric", "Current", "Min", "Max", "Unit", "Status"])
        lay.addWidget(self.tbl_gpu)

    def _build_disk_tab(self, lay):
        self.tbl_disk = _make_table(["Drive", "Mount", "Used GB", "Total GB", "R MB/s", "W MB/s", "R IOPS", "Health", "Temp"])
        lay.addWidget(QLabel("Drive I/O & SMART Health:"))
        lay.addWidget(self.tbl_disk)
        self.tbl_smart = _make_table(["Device", "Model", "Health", "Temp °C", "Capacity", "Interface", "Notes"])
        lay.addWidget(QLabel("SMART Data:"))
        lay.addWidget(self.tbl_smart)

    def _build_mb_tab(self, lay):
        self.tbl_mb_temps = _make_table(["Sensor", "Current °C", "High", "Critical", "Status"])
        lay.addWidget(QLabel("Temperatures:"))
        lay.addWidget(self.tbl_mb_temps)
        self.tbl_mb_sys = _make_table(["Property", "Value"])
        lay.addWidget(QLabel("System Info:"))
        lay.addWidget(self.tbl_mb_sys)

    def _build_usb_tab(self, lay):
        self.tbl_usb_dev = _make_table(["Type", "Name", "Status", "Wireless", "Bluetooth", "Error"])
        lay.addWidget(QLabel("Input / USB Devices:"))
        lay.addWidget(self.tbl_usb_dev)
        self.tbl_usb_hubs = _make_table(["Hub/Controller", "Description", "Manufacturer", "Status"])
        lay.addWidget(QLabel("USB Hubs & Controllers:"))
        lay.addWidget(self.tbl_usb_hubs)

    def _build_services_tab(self, lay):
        top = QHBoxLayout()
        self.svc_search = QLineEdit()
        self.svc_search.setPlaceholderText("Filter services...")
        self.svc_search.textChanged.connect(self._filter_services)
        top.addWidget(self.svc_search)
        lay.addLayout(top)
        self.tbl_svc = _make_table(["Name", "Display Name", "Status", "Start Type", "PID", "User", "Binary"])
        lay.addWidget(self.tbl_svc)

    def _build_processes_tab(self, lay):
        top = QHBoxLayout()
        self.proc_search = QLineEdit()
        self.proc_search.setPlaceholderText("Filter processes...")
        top.addWidget(self.proc_search)
        self.proc_sort = QPushButton("Sort by CPU")
        self.proc_sort.clicked.connect(lambda: self.tbl_proc.sortItems(2, Qt.DescendingOrder))
        top.addWidget(self.proc_sort)
        lay.addLayout(top)
        self.tbl_proc = _make_table(["PID", "Name", "CPU%", "RAM MB", "RAM%", "R MB", "W MB", "Threads", "User", "Status"])
        lay.addWidget(self.tbl_proc)

    def _build_fileaccess_tab(self, lay):
        top = QHBoxLayout()
        lbl = QLabel("Live File Access by Process:")
        lbl.setStyleSheet(f"color:{ACCENT};font-weight:bold;")
        top.addWidget(lbl)
        top.addStretch()
        self.fa_filter = QLineEdit()
        self.fa_filter.setPlaceholderText("Filter by process or path...")
        self.fa_filter.setFixedWidth(220)
        top.addWidget(self.fa_filter)
        lay.addLayout(top)

        splitter = QSplitter(Qt.Vertical)

        # Open files per process
        self.tbl_fa_procs = _make_table(["PID", "Process", "User", "Open Files", "Suspicious Paths"])
        splitter.addWidget(self.tbl_fa_procs)

        # Real-time FS events
        evt_label = QLabel("Real-time FS Events (Watched Dirs):")
        evt_label.setStyleSheet(f"color:{ACCENT};font-weight:bold;")
        self.tbl_fa_events = _make_table(["Time", "Event", "Path", "Dir", "Suspicious"])
        evt_widget = QWidget()
        evt_lay = QVBoxLayout(evt_widget)
        evt_lay.setContentsMargins(0, 4, 0, 0)
        evt_lay.addWidget(evt_label)
        evt_lay.addWidget(self.tbl_fa_events)
        splitter.addWidget(evt_widget)

        # Suspicious alerts
        sus_label = QLabel("Suspicious Activity Alerts:")
        sus_label.setStyleSheet(f"color:{RED};font-weight:bold;")
        self.tbl_fa_sus = _make_table(["Time", "Type", "Severity", "Message"])
        sus_widget = QWidget()
        sus_lay = QVBoxLayout(sus_widget)
        sus_lay.setContentsMargins(0, 4, 0, 0)
        sus_lay.addWidget(sus_label)
        sus_lay.addWidget(self.tbl_fa_sus)
        splitter.addWidget(sus_widget)

        splitter.setSizes([300, 250, 150])
        lay.addWidget(splitter)

    def _build_eventlog_tab(self, lay):
        self.tbl_evlog = _make_table(["Type", "Source", "Event ID", "Time", "Message"])
        lay.addWidget(self.tbl_evlog)

    def _build_apps_tab(self, lay):
        top = QHBoxLayout()
        self.app_search = QLineEdit()
        self.app_search.setPlaceholderText("Search installed apps...")
        top.addWidget(self.app_search)
        lay.addLayout(top)
        self.tbl_apps = _make_table(["Name", "Version", "Publisher", "Install Date", "Size MB"])
        lay.addWidget(self.tbl_apps)

    def _build_temp_tab(self, lay):
        self.tbl_temp = _make_table(["Path", "Files", "Total Size MB", "Oldest File", "Newest File"])
        lay.addWidget(self.tbl_temp)

    def _build_registry_tab(self, lay):
        self.tbl_reg = _make_table(["Name", "Value", "Hive", "Flag"])
        lay.addWidget(QLabel("Startup Registry Entries:"))
        lay.addWidget(self.tbl_reg)
        self.tbl_reg_sus = _make_table(["Name", "Value", "Flag"])
        lay.addWidget(QLabel("⚠ Suspicious Entries:"))
        lay.addWidget(self.tbl_reg_sus)

    def _build_threads_tab(self, lay):
        self.tbl_threads = _make_table(["PID", "Process", "Thread Count"])
        lay.addWidget(self.tbl_threads)

    def _build_kernel_tab(self, lay):
        self.tbl_kernel = _make_table(["Property", "Value"])
        lay.addWidget(self.tbl_kernel)

    def _build_interrupts_tab(self, lay):
        self.tbl_intr = _make_table(["Metric", "Value", "Status"])
        lay.addWidget(self.tbl_intr)

    def _build_network_tab(self, lay):
        self.tbl_net = _make_table(["Adapter", "RX MB/s", "TX MB/s", "Errors In", "Errors Out", "Drops In", "Drops Out"])
        lay.addWidget(self.tbl_net)

    # ── REFRESH ───────────────────────────────────────────────────────────────
    def _refresh(self):
        if not self.monitor or not self.isVisible() or self.isMinimized():
            return
        v = self.monitor.get_vitals_snapshot()
        if not v:
            return
        self._update_cards(v)
        tab_idx = self.tabs.currentIndex()
        refreshers = [
            self._update_cpu, self._update_gpu, self._update_disk,
            self._update_mb, self._update_usb, self._update_services,
            self._update_processes, self._update_fileaccess,
            self._update_eventlog, self._update_apps, self._update_temp,
            self._update_registry, self._update_threads, self._update_kernel,
            self._update_interrupts, self._update_network,
        ]
        if tab_idx < len(refreshers):
            try:
                refreshers[tab_idx](v)
            except Exception as e:
                print(f"[DASHBOARD TAB REFRESH ERROR] Tab {tab_idx}: {e}")

    def _update_cards(self, v):
        c = v.get("cpu") or {}
        g = v.get("gpu") or {}
        mb = v.get("motherboard") or {}
        d = v.get("disk") or {}
        intr = v.get("interrupts") or {}
        kern = v.get("kernel") or {}

        cpu_val = c.get("usage_total", 0) or 0
        gpu_val = g.get("usage_pct", 0) or 0
        ram_val = mb.get("ram", {}).get("usage_pct", 0) if mb.get("ram") else 0
        r_mb = d.get("max_read_mbps") or 0
        w_mb = d.get("max_write_mbps") or 0
        disk_val = max(r_mb, w_mb)
        irq_val = intr.get("interrupts_per_sec", 0) or 0
        procs_val = kern.get("process_count", 0) or 0

        self.card_cpu.update_val(f"{cpu_val:.1f}", "%", _status_color(cpu_val, 70, 90))
        self.card_gpu.update_val(f"{gpu_val:.1f}", "%", _status_color(gpu_val, 75, 90))
        self.card_ram.update_val(f"{ram_val:.1f}", "%", _status_color(ram_val, 75, 90))
        self.card_disk.update_val(f"{disk_val:.1f}", "MB/s", _status_color(disk_val, 150, 300))
        self.card_irq.update_val(f"{irq_val:,}", "/s", _status_color(irq_val, 30000, 60000))
        self.card_procs.update_val(str(procs_val), "", GREY)

    def _fill_table(self, table, rows):
        table.setRowCount(len(rows))
        for r, row_data in enumerate(rows):
            for c, item in enumerate(row_data):
                if isinstance(item, QTableWidgetItem):
                    table.setItem(r, c, item)
                else:
                    table.setItem(r, c, _cell(item))

    def _update_cpu(self, v):
        c = v.get("cpu") or {}
        cpu_val = c.get("usage_total", 0) or 0
        rows = [
            ["Total Usage", f"{cpu_val:.1f}", "—", "—", "%", _cell("OK" if cpu_val < 85 else "HIGH", _status_color(cpu_val, 70, 85))],
            ["Frequency", f"{c.get('freq_current_mhz', 0):.0f}", f"{c.get('freq_min_mhz', 0):.0f}", f"{c.get('freq_max_mhz', 0):.0f}", "MHz", _cell("OK", GREEN)],
            ["User %", f"{c.get('user_pct', 0):.1f}", "—", "—", "%", _cell("OK", GREEN)],
            ["System %", f"{c.get('system_pct', 0):.1f}", "—", "—", "%", _cell("OK", GREEN)],
            ["Idle %", f"{c.get('idle_pct', 0):.1f}", "—", "—", "%", _cell("OK", GREEN)],
            ["Interrupt %", f"{c.get('interrupt_pct', 0):.1f}", "—", "—", "%", _cell("WARN" if c.get('interrupt_pct', 0) > 10 else "OK", _status_color(c.get('interrupt_pct', 0), 10, 25))],
            ["DPC %", f"{c.get('dpc_pct', 0):.1f}", "—", "—", "%", _cell("WARN" if c.get('dpc_pct', 0) > 5 else "OK", _status_color(c.get('dpc_pct', 0), 5, 15))],
            ["Power Est.", f"{c.get('power_est_w', 0):.1f}", "—", "—", "W", _cell("OK", GREY)],
            ["Ctx Switches", f"{c.get('ctx_switches', 0):,}", "—", "—", "", _cell("OK", GREY)],
            ["Interrupts", f"{c.get('interrupts', 0):,}", "—", "—", "", _cell("OK", GREY)],
            ["Syscalls", f"{c.get('syscalls', 0):,}", "—", "—", "", _cell("OK", GREY)],
        ]
        for i, core_pct in enumerate(c.get("usage_per_core", [])):
            rows.append([f"Core {i}", f"{core_pct:.1f}", "—", "—", "%",
                         _cell("HIGH" if core_pct > 90 else "OK", _status_color(core_pct, 75, 90))])
        for name, info in c.get("temperatures", {}).items():
            if isinstance(info, dict):
                t = info.get("current")
            else:
                t = info
            rows.append([f"Temp: {name}", f"{t:.1f}" if t else "—", "—", "—", "°C",
                         _cell("HOT" if t and t > 80 else "OK", _status_color(t or 0, 75, 90))])
        self._fill_table(self.tbl_cpu, rows)

    def _update_gpu(self, v):
        gpus = v.get("gpu", {}).get("gpus", [])
        rows = []
        for g in gpus:
            rows += [
                [g.get("name", "GPU"), f"{g.get('usage_pct', 0) or 0:.1f}", "—", "—", "%",
                 _cell("HIGH" if (g.get("usage_pct") or 0) > 90 else "OK", _status_color(g.get("usage_pct") or 0, 75, 90))],
                ["VRAM Used", f"{g.get('mem_used_mb', 0) or 0:.0f}", "—", f"{g.get('mem_total_mb', 0) or 0:.0f}", "MB",
                 _cell(f"{g.get('mem_usage_pct', 0) or 0:.1f}%", _status_color(g.get("mem_usage_pct") or 0, 70, 90))],
                ["Temperature", f"{g.get('temp_c', 'N/A')}", "—", "—", "°C",
                 _cell("HOT" if g.get("temp_c") and g.get("temp_c") > 80 else "OK",
                        _status_color(g.get("temp_c") or 0, 75, 90))],
                ["Driver", g.get("driver", "N/A"), "—", "—", "", _cell("", GREY)],
                ["Vendor", g.get("vendor", "N/A"), "—", "—", "", _cell("", GREY)],
            ]
        if not rows:
            rows = [["No GPU data", "—", "—", "—", "", _cell("", GREY)]]
        self._fill_table(self.tbl_gpu, rows)

    def _update_disk(self, v):
        d = v.get("disk", {})
        disk_rows = []
        for dev, info in d.get("disks", {}).items():
            if not isinstance(info, dict):
                continue
            disk_rows.append([
                dev,
                info.get("mountpoint", ""),
                f"{info.get('used_gb', 0):.1f}",
                f"{info.get('total_gb', 0):.1f}",
                f"{info.get('read_rate_mbps', 0):.2f}",
                f"{info.get('write_rate_mbps', 0):.2f}",
                f"{info.get('read_iops', 0):.0f}",
                "—",
                "—",
            ])
        self._fill_table(self.tbl_disk, disk_rows)
        smart_rows = []
        for name, info in d.get("smart", {}).items():
            if name == "error" or not isinstance(info, dict):
                continue
            smart_rows.append([
                name, info.get("model", "—"), info.get("health", "—"),
                str(info.get("temperature", "—")), info.get("capacity", "—"),
                info.get("interface", "—"),
                "; ".join((info.get("messages") or [])[:2])
            ])
        self._fill_table(self.tbl_smart, smart_rows)

    def _update_mb(self, v):
        mb = v.get("motherboard", {})
        temp_rows = []
        for name, info in mb.get("temperatures", {}).items():
            if isinstance(info, dict):
                t = info.get("current")
                h = info.get("high")
                cr = info.get("critical")
            else:
                t, h, cr = info, None, None
            temp_rows.append([name, f"{t:.1f}" if t else "—",
                               f"{h:.1f}" if h else "—", f"{cr:.1f}" if cr else "—",
                               _cell("HOT" if t and t > 85 else "OK", _status_color(t or 0, 75, 90))])
        self._fill_table(self.tbl_mb_temps, temp_rows)
        sys_info = {**mb.get("system", {})}
        ram = mb.get("ram", {})
        if ram:
            sys_info["RAM Used GB"] = f"{ram.get('used_gb',0):.1f}"
            sys_info["RAM Total GB"] = f"{ram.get('total_gb',0):.1f}"
            sys_info["RAM Usage %"] = f"{ram.get('usage_pct',0):.1f}"
        swap = mb.get("swap", {})
        if swap:
            sys_info["Swap Used GB"] = f"{swap.get('used_gb',0):.2f}"
            sys_info["Swap Total GB"] = f"{swap.get('total_gb',0):.2f}"
        self._fill_table(self.tbl_mb_sys, [[k, v] for k, v in sys_info.items()])

    def _update_usb(self, v):
        usb = v.get("usb", {})
        dev_rows = []
        for d in usb.get("devices", []):
            dev_rows.append([
                d.get("type", ""), d.get("name", ""), d.get("status", ""),
                "Yes" if d.get("is_wireless") else "No",
                "Yes" if d.get("is_bluetooth") else "No",
                str(d.get("error_code", "")) or "—"
            ])
        self._fill_table(self.tbl_usb_dev, dev_rows)
        hub_rows = []
        for h in usb.get("hubs", []) + usb.get("controllers", []):
            hub_rows.append([h.get("name", ""), h.get("description", ""),
                             h.get("manufacturer", ""), h.get("status", "")])
        self._fill_table(self.tbl_usb_hubs, hub_rows)

    def _update_services(self, v):
        svcs = v.get("services", {}).get("services", [])
        filt = self.svc_search.text().lower()
        rows = []
        for s in svcs:
            if filt and filt not in (s.get("name","") + s.get("display_name","")).lower():
                continue
            rows.append([s.get("name",""), s.get("display_name",""), s.get("status",""),
                         s.get("start_type",""), str(s.get("pid","") or "—"),
                         s.get("username",""), (s.get("binpath","") or "")[:60]])
        self._fill_table(self.tbl_svc, rows)

    def _filter_services(self, text):
        if self.monitor:
            self._update_services(self.monitor.get_vitals_snapshot())

    def _update_processes(self, v):
        procs = v.get("processes", {}).get("processes", [])
        rows = []
        for p in procs[:200]:
            rows.append([str(p.get("pid","")), p.get("name",""),
                         f"{p.get('cpu_pct',0):.1f}", f"{p.get('ram_mb',0):.1f}",
                         f"{p.get('ram_pct',0):.1f}", f"{p.get('read_mb',0):.2f}",
                         f"{p.get('write_mb',0):.2f}", str(p.get("threads",0)),
                         p.get("username",""), p.get("status","")])
        self._fill_table(self.tbl_proc, rows)

    def _update_fileaccess(self, v):
        fa = v.get("file_access", {})

        # Open files per process
        proc_rows = []
        filt = self.fa_filter.text().lower()
        for p in fa.get("open_files_by_proc", []):
            if filt and filt not in (p.get("name","") + " ".join(p.get("files",[]))).lower():
                continue
            sus_files = p.get("suspicious_files", [])
            proc_rows.append([
                str(p.get("pid","")), p.get("name",""), p.get("username",""),
                str(p.get("file_count", 0)),
                _cell(str(len(sus_files)) if sus_files else "0",
                      RED if sus_files else GREEN)
            ])
        self._fill_table(self.tbl_fa_procs, proc_rows)

        # FS events
        ev_rows = []
        for ev in list(fa.get("recent_fs_events", []))[-100:]:
            sus = ev.get("suspicious", False)
            ev_rows.append([
                ev.get("time",""), ev.get("event",""),
                _cell(ev.get("path","")[-80:], RED if sus else TEXT),
                ev.get("dir","")[-40:],
                _cell("⚠ YES" if sus else "—", RED if sus else GREY)
            ])
        self._fill_table(self.tbl_fa_events, ev_rows)

        # Suspicious alerts
        sus_rows = []
        for s in fa.get("suspicious_events", []):
            sus_rows.append([
                s.get("time",""), s.get("type",""),
                _cell(s.get("severity",""), RED if s.get("severity")=="CRITICAL" else ORANGE),
                s.get("message","")[:120]
            ])
        self._fill_table(self.tbl_fa_sus, sus_rows)

    def _update_eventlog(self, v):
        entries = v.get("eventlog", {}).get("entries", [])
        rows = []
        for e in entries:
            color = RED if e.get("type") == "Error" else ORANGE
            rows.append([
                _cell(e.get("type",""), color), e.get("source",""),
                str(e.get("event_id","")), e.get("time","")[:16],
                e.get("message","")[:100]
            ])
        self._fill_table(self.tbl_evlog, rows)

    def _update_apps(self, v):
        apps = v.get("apps", {}).get("apps", [])
        filt = self.app_search.text().lower()
        rows = [[a.get("name",""), a.get("version",""), a.get("publisher",""),
                 a.get("install_date",""), str(a.get("size_mb",""))]
                for a in apps if not filt or filt in a.get("name","").lower()]
        self._fill_table(self.tbl_apps, rows)

    def _update_temp(self, v):
        folders = v.get("temp_folders", {}).get("folders", [])
        rows = []
        for f in folders:
            rows.append([f.get("path",""), str(f.get("file_count","")),
                         f"{f.get('total_size_mb',0):.1f}",
                         str(f.get("oldest_file",""))[:16],
                         str(f.get("newest_file",""))[:16]])
        self._fill_table(self.tbl_temp, rows)

    def _update_registry(self, v):
        reg = v.get("registry", {})
        rows = [[e.get("name",""), e.get("value","")[:80], e.get("hive",""), e.get("flag","")]
                for e in reg.get("startup_entries", [])]
        self._fill_table(self.tbl_reg, rows)
        sus_rows = [[e.get("name",""), e.get("value","")[:80], e.get("flag","")]
                    for e in reg.get("suspicious", [])]
        self._fill_table(self.tbl_reg_sus, sus_rows)

    def _update_threads(self, v):
        thrd = v.get("threads", {})
        rows = [[str(p.get("pid","")), p.get("name",""), str(p.get("num_threads",""))]
                for p in thrd.get("by_process", [])]
        self._fill_table(self.tbl_threads, rows)

    def _update_kernel(self, v):
        kern = v.get("kernel", {})
        rows = [[k, str(val)] for k, val in kern.items() if k != "timestamp"]
        self._fill_table(self.tbl_kernel, rows)

    def _update_interrupts(self, v):
        intr = v.get("interrupts", {})
        irq = intr.get("interrupts_per_sec", 0)
        dpc = intr.get("dpc_per_sec", 0)
        rows = [
            ["Interrupts/sec", f"{irq:,}", _cell("HIGH" if irq > 50000 else "OK", _status_color(irq, 30000, 60000))],
            ["DPC/sec", f"{dpc:,}", _cell("HIGH" if dpc > 10000 else "OK", _status_color(dpc, 8000, 15000))],
            ["IRQ Time %", f"{intr.get('pct_interrupt',0):.2f}", _cell("WARN" if intr.get('pct_interrupt',0)>10 else "OK", _status_color(intr.get('pct_interrupt',0), 10, 20))],
            ["DPC Time %", f"{intr.get('pct_dpc',0):.2f}", _cell("WARN" if intr.get('pct_dpc',0)>5 else "OK", _status_color(intr.get('pct_dpc',0), 5, 15))],
        ]
        self._fill_table(self.tbl_intr, rows)

    def _update_network(self, v):
        adapters = v.get("usb", {}).get("network_adapters", [])
        rows = [[a.get("name",""), f"{a.get('rx_rate_mbps',0):.3f}",
                 f"{a.get('tx_rate_mbps',0):.3f}", str(a.get("errors_in",0)),
                 str(a.get("errors_out",0)), str(a.get("drop_in",0)), str(a.get("drop_out",0))]
                for a in adapters]
        self._fill_table(self.tbl_net, rows)
