"""
KaunHaiBe - Matrix Terminal #1: Problem Tracker
Live scrolling feed of anomalies, spikes, errors, suspicious activity
Green-on-black Matrix aesthetic
"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel, QComboBox, QLineEdit, QSlider
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QTextCursor

MATRIX_STYLE = """
QMainWindow, QWidget { background-color: #000000; color: #00ff41; }
QTextEdit {
    background-color: #020c02;
    color: #00ff41;
    border: 1px solid #004d10;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
    selection-background-color: #003300;
}
QPushButton {
    background: #001a00;
    color: #00ff41;
    border: 1px solid #004d10;
    padding: 4px 12px;
    font-family: Consolas;
    font-size: 11px;
}
QPushButton:hover { background: #003300; border-color: #00ff41; }
QComboBox {
    background: #001a00;
    color: #00ff41;
    border: 1px solid #004d10;
    padding: 2px 6px;
    font-family: Consolas;
    font-size: 11px;
}
QComboBox QAbstractItemView {
    background: #001a00;
    color: #00ff41;
    selection-background-color: #003300;
}
QLabel { color: #00ff41; font-family: Consolas; font-size: 11px; }
QLineEdit {
    background: #001a00;
    color: #00ff41;
    border: 1px solid #004d10;
    padding: 3px 6px;
    font-family: Consolas;
    font-size: 11px;
}
"""

LEVEL_COLORS = {
    "CRITICAL": "#ff0000",
    "WARNING":  "#ffaa00",
    "INFO":     "#00ff41",
    "SPIKE":    "#ffdc00",
    "FILE":     "#00ccff",
    "NETWORK":  "#00aaff",
    "RISK":     "#ff6600",
    "SEC":      "#ff00ff",
    "SYSTEM":   "#88ff88",
}


def _level_color(msg: str) -> str:
    mu = msg.upper()
    for key, color in LEVEL_COLORS.items():
        if key in mu:
            return color
    return "#00ff41"


class TerminalAlert(QMainWindow):
    def __init__(self, monitor_engine=None, parent=None):
        super().__init__(parent)
        self.monitor = monitor_engine
        self._all_events = []
        self._paused = False

        self.setWindowTitle("KaunHaiBe — Problem Terminal [Matrix Mode]")
        self.setMinimumSize(900, 600)
        self.setStyleSheet(MATRIX_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("▶ KaunHaiBe :: PROBLEM TRACKER")
        title.setStyleSheet("color:#00ff41;font-size:14px;font-weight:bold;font-family:Consolas;")
        self.lbl_count = QLabel("Events: 0")
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(self.lbl_count)
        root.addLayout(hdr)

        # Controls
        ctrl = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "CRITICAL", "WARNING", "SPIKE", "FILE", "RISK", "SEC", "NETWORK"])
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search events...")
        self.search_box.textChanged.connect(self._apply_filter)
        self.search_box.setFixedWidth(180)
        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_clear = QPushButton("🗑 Clear")
        self.btn_clear.clicked.connect(self._clear)
        ctrl.addWidget(QLabel("Filter:"))
        ctrl.addWidget(self.filter_combo)
        ctrl.addWidget(self.search_box)
        ctrl.addSpacing(10)

        # Font size slider
        font_lbl = QLabel("Font Size:")
        font_val_lbl = QLabel("11px")
        font_val_lbl.setFixedWidth(30)
        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(8, 24)
        self.font_slider.setValue(11)
        self.font_slider.setFixedWidth(80)
        self.font_slider.setToolTip("Adjust terminal text font size (8px - 24px)")
        self.font_slider.valueChanged.connect(lambda v: (self._set_font_size(v), font_val_lbl.setText(f"{v}px")))
        ctrl.addWidget(font_lbl)
        ctrl.addWidget(self.font_slider)
        ctrl.addWidget(font_val_lbl)

        ctrl.addStretch()
        ctrl.addWidget(self.btn_pause)
        ctrl.addWidget(self.btn_clear)
        root.addLayout(ctrl)

        # Terminal output
        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setLineWrapMode(QTextEdit.NoWrap)
        root.addWidget(self.terminal)

        # Status bar
        self.status_bar = QLabel("● LIVE")
        self.status_bar.setStyleSheet("color:#00ff41;font-size:10px;")
        root.addWidget(self.status_bar)

        # Boot message
        self._print_line("=" * 80, "#004d10")
        self._print_line("  KaunHaiBe PROBLEM TERMINAL :: MATRIX MODE  v1.0", "#00ff41")
        self._print_line(f"  Monitoring: CPU | GPU | Disk | Network | File | Security | Registry", "#88ff88")
        self._print_line("=" * 80, "#004d10")
        self._print_line("  Waiting for system events...", "#00aa20")
        self._print_line("", "#00ff41")

        # Poll timer
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(800)
        self.poll_timer.timeout.connect(self._poll_events)
        self.poll_timer.start()

        # Blink timer for live indicator
        self._blink = True
        self.blink_timer = QTimer(self)
        self.blink_timer.setInterval(600)
        self.blink_timer.timeout.connect(self._blink_status)
        self.blink_timer.start()

    def _blink_status(self):
        self._blink = not self._blink
        if self._paused:
            self.status_bar.setText("⏸ PAUSED")
            self.status_bar.setStyleSheet("color:#ffaa00;font-size:10px;")
        else:
            sym = "●" if self._blink else "○"
            self.status_bar.setText(f"{sym} LIVE  |  Events: {len(self._all_events)}")
            self.status_bar.setStyleSheet(f"color:{'#00ff41' if self._blink else '#004d10'};font-size:10px;")

    def _poll_events(self):
        if self._paused or not self.monitor or not self.isVisible() or self.isMinimized():
            return
        events = self.monitor.get_recent_events(200)
        new_events = [e for e in events if e not in self._all_events]

        # Also grab from res_access and file_access
        v = self.monitor.get_vitals_snapshot()
        fa = v.get("file_access", {})
        res = v.get("res_access", {})

        for sus in fa.get("suspicious_events", [])[-5:]:
            msg = f"[FILE] {sus.get('type','')} — {sus.get('message', sus.get('path',''))}"
            entry = {"time": sus.get("time",""), "type": "file_suspicious", "message": msg}
            if entry not in self._all_events:
                new_events.append(entry)

        for flag in res.get("flagged_processes", [])[-5:]:
            flags = ", ".join(flag.get("risk_flags", []))
            msg = f"[RISK:{flag.get('risk_score',0)}/10] {flag.get('name','?')} PID:{flag.get('pid','')} — {flags}"
            entry = {"time": flag.get("flagged_at", ""), "type": "risk", "message": msg}
            if entry not in self._all_events:
                new_events.append(entry)

        for sec_ev in res.get("security_events", [])[-5:]:
            msg = f"[SEC:{sec_ev.get('event_id','')}] {sec_ev.get('description','')} — {sec_ev.get('source','')}"
            entry = {"time": sec_ev.get("time",""), "type": "security", "message": msg}
            if entry not in self._all_events:
                new_events.append(entry)

        if new_events:
            self._all_events.extend(new_events)
            self._all_events = self._all_events[-1000:]
            self._apply_filter()
            self.lbl_count.setText(f"Events: {len(self._all_events)}")

    def _apply_filter(self):
        filt = self.filter_combo.currentText()
        search = self.search_box.text().lower()

        filtered = self._all_events
        if filt != "All":
            filtered = [e for e in filtered if filt.upper() in e.get("message","").upper()
                        or filt.upper() in e.get("type","").upper()]
        if search:
            filtered = [e for e in filtered if search in e.get("message","").lower()]

        self.terminal.clear()
        for e in filtered[-500:]:
            t = e.get("time","")
            msg = e.get("message","")
            color = _level_color(msg)
            self._print_line(f"[{t}] {msg}", color)

        # Auto-scroll to bottom
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.terminal.setTextCursor(cursor)

    def _print_line(self, text: str, color: str = "#00ff41"):
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        self.terminal.setTextCursor(cursor)

    def push_alert(self, msg: str):
        """External call to push an alert message."""
        import time as _time
        t = _time.strftime("%H:%M:%S")
        entry = {"time": t, "type": "alert", "message": msg}
        self._all_events.append(entry)
        if not self._paused:
            color = _level_color(msg)
            self._print_line(f"[{t}] {msg}", color)
            cursor = self.terminal.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.terminal.setTextCursor(cursor)

    def _toggle_pause(self):
        self._paused = not self._paused
        self.btn_pause.setText("▶ Resume" if self._paused else "⏸ Pause")

    def _clear(self):
        self._all_events.clear()
        self.terminal.clear()

    def _set_font_size(self, size_px: int):
        self.terminal.setStyleSheet(f"""
            background-color: #020c02;
            color: #00ff41;
            border: 1px solid #004d10;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: {size_px}px;
            selection-background-color: #003300;
        """)
