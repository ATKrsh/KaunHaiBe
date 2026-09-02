"""
KaunHaiBe - Matrix Terminal #2: AI Chat
Local AI chat powered by qwen2.5:14b via Ollama
Matrix movie aesthetic with cyan/green streaming text
"""
import time as _time
import threading

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel, QLineEdit, QSplitter, QSlider
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QTextCursor

AI_STYLE = """
QMainWindow, QWidget { background-color: #00020a; color: #00eeff; }
QTextEdit {
    background-color: #00020a;
    color: #00eeff;
    border: 1px solid #003340;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
    selection-background-color: #002233;
}
QLineEdit {
    background: #00060f;
    color: #00eeff;
    border: 1px solid #004455;
    padding: 6px 10px;
    font-family: Consolas;
    font-size: 12px;
    border-radius: 4px;
}
QLineEdit:focus { border-color: #00eeff; }
QPushButton {
    background: #00060f;
    color: #00eeff;
    border: 1px solid #004455;
    padding: 6px 16px;
    font-family: Consolas;
    font-size: 11px;
    border-radius: 4px;
}
QPushButton:hover { background: #001a2a; border-color: #00eeff; }
QPushButton#send_btn {
    background: #003344;
    color: #00eeff;
    border: 1px solid #00eeff;
    font-weight: bold;
}
QPushButton#send_btn:hover { background: #004455; }
QLabel { color: #00eeff; font-family: Consolas; font-size: 11px; }
"""

QUICK_CMDS = [
    "Why is my PC lagging?",
    "Show top CPU hogs",
    "Show top RAM consumers",
    "Analyze network activity",
    "Check disk health",
    "Any suspicious processes?",
    "DPC/interrupt analysis",
    "What's accessing credentials?",
    "Show permission events",
    "Generate system report",
]


class _TokenWorker(QObject):
    token_ready = pyqtSignal(str)
    done        = pyqtSignal(str)

    def __init__(self, ai_engine, message, vitals):
        super().__init__()
        self._ai = ai_engine
        self._msg = message
        self._vitals = vitals
        self._buffer = []

    def run(self):
        def _stream(token):
            self._buffer.append(token)
            self.token_ready.emit(token)

        self._ai.set_vitals_context(self._vitals)
        result = self._ai.chat(self._msg, stream_callback=_stream)
        self.done.emit(result)


class TerminalAI(QMainWindow):
    def __init__(self, monitor_engine=None, ai_engine=None, parent=None):
        super().__init__(parent)
        self.monitor = monitor_engine
        self.ai      = ai_engine
        self._busy   = False
        self._worker_thread = None

        self.setWindowTitle("KaunHaiBe — AI Chat Terminal [qwen2.5:14b]")
        self.setMinimumSize(960, 680)
        self.setStyleSheet(AI_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("◈ KaunHaiBe :: AI DIAGNOSTICS TERMINAL")
        title.setStyleSheet("color:#00eeff;font-size:14px;font-weight:bold;font-family:Consolas;")
        self.lbl_model = QLabel("Model: detecting...")
        self.lbl_model.setStyleSheet("color:#005566;font-size:10px;")
        # Font size slider
        font_lbl = QLabel("Font Size:")
        font_val_lbl = QLabel("11px")
        font_val_lbl.setFixedWidth(30)
        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(8, 24)
        self.font_slider.setValue(11)
        self.font_slider.setFixedWidth(80)
        self.font_slider.setToolTip("Adjust AI chat font size (8px - 24px)")
        self.font_slider.valueChanged.connect(lambda v: (self._set_font_size(v), font_val_lbl.setText(f"{v}px")))

        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(font_lbl)
        hdr.addWidget(self.font_slider)
        hdr.addWidget(font_val_lbl)
        hdr.addSpacing(15)
        hdr.addWidget(self.lbl_model)
        root.addLayout(hdr)

        # Splitter: chat | quick commands
        splitter = QSplitter(Qt.Horizontal)

        # Chat area
        chat_widget = QWidget()
        chat_lay = QVBoxLayout(chat_widget)
        chat_lay.setContentsMargins(0, 0, 0, 0)
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        chat_lay.addWidget(self.chat_display)

        # Input area
        input_row = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Ask AI about your system... (Enter to send)")
        self.input_box.returnPressed.connect(self._send)
        self.send_btn = QPushButton("⏎ SEND")
        self.send_btn.setObjectName("send_btn")
        self.send_btn.clicked.connect(self._send)
        self.send_btn.setFixedWidth(90)
        input_row.addWidget(self.input_box)
        input_row.addWidget(self.send_btn)
        chat_lay.addLayout(input_row)
        splitter.addWidget(chat_widget)

        # Quick commands sidebar
        quick_widget = QWidget()
        quick_widget.setFixedWidth(200)
        quick_lay = QVBoxLayout(quick_widget)
        quick_lay.setContentsMargins(4, 0, 0, 0)
        quick_lay.addWidget(QLabel("Quick Commands:"))
        for cmd in QUICK_CMDS:
            btn = QPushButton(cmd)
            btn.setStyleSheet("text-align:left;padding:4px 8px;font-size:10px;")
            btn.clicked.connect(lambda _, c=cmd: self._quick_send(c))
            quick_lay.addWidget(btn)
        quick_lay.addStretch()

        # System stats mini-display
        self.stats_display = QTextEdit()
        self.stats_display.setReadOnly(True)
        self.stats_display.setMaximumHeight(150)
        self.stats_display.setStyleSheet("font-size:9px;color:#005566;border:1px solid #002233;")
        quick_lay.addWidget(QLabel("Live Stats:"))
        quick_lay.addWidget(self.stats_display)
        splitter.addWidget(quick_widget)

        splitter.setSizes([720, 200])
        root.addWidget(splitter)

        # Boot sequence
        self._print("=" * 70, "#003344")
        self._print("  KaunHaiBe AI Terminal  —  Powered by qwen2.5:14b  v1.0", "#00eeff")
        self._print("  Local AI running on: RTX 3050 8GB + 64GB RAM", "#005566")
        self._print("=" * 70, "#003344")
        self._print("", "#00eeff")
        self._print("  Initializing AI engine...", "#005566")
        self._print("  Type your question or use Quick Commands on the right.", "#004455")
        self._print("", "#00eeff")

        # Model check timer
        self.model_check_timer = QTimer(self)
        self.model_check_timer.setInterval(2000)
        self.model_check_timer.timeout.connect(self._check_model)
        self.model_check_timer.start()

        # Stats update timer
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(2000)
        self.stats_timer.timeout.connect(self._update_stats)
        self.stats_timer.start()

    def _check_model(self):
        if not self.ai:
            return
        model = self.ai.get_model_name()
        if self.ai.is_online():
            self.lbl_model.setText(f"✓ {model}")
            self.lbl_model.setStyleSheet("color:#00ff41;font-size:10px;font-family:Consolas;")
            self._print(f"  ✓ AI Online: {model}", "#00ff41")
            self.model_check_timer.stop()
        else:
            self.lbl_model.setText(f"⟳ Rule-Based (Ollama loading...)")
            self.lbl_model.setStyleSheet("color:#ffaa00;font-size:10px;font-family:Consolas;")

    def _update_stats(self):
        if not self.monitor:
            return
        try:
            v = self.monitor.get_vitals_snapshot()
            c  = v.get("cpu", {})
            g  = v.get("gpu", {})
            mb = v.get("motherboard", {})
            d  = v.get("disk", {})
            intr = v.get("interrupts", {})

            ram = mb.get("ram", {})
            text = (
                f"CPU:  {c.get('usage_total',0):.1f}%  {c.get('freq_current_mhz',0):.0f}MHz\n"
                f"GPU:  {g.get('usage_pct',0) or 0:.1f}%  {g.get('temp_c','?')}°C\n"
                f"RAM:  {ram.get('usage_pct',0):.1f}% ({ram.get('used_gb',0):.1f}/{ram.get('total_gb',0):.1f}GB)\n"
                f"Disk: R:{d.get('max_read_mbps',0):.1f} W:{d.get('max_write_mbps',0):.1f} MB/s\n"
                f"IRQ:  {intr.get('interrupts_per_sec',0):,}/s\n"
                f"DPC:  {intr.get('dpc_per_sec',0):,}/s\n"
            )
            self.stats_display.setText(text)
        except Exception:
            pass

    def _quick_send(self, cmd: str):
        self.input_box.setText(cmd)
        self._send()

    def _send(self):
        if self._busy or not self.ai:
            return
        msg = self.input_box.text().strip()
        if not msg:
            return
        self.input_box.clear()

        # Print user message
        t = _time.strftime("%H:%M:%S")
        self._print(f"\n[{t}] YOU › {msg}", "#00eeff")
        self._print("─" * 60, "#002233")

        # Print AI prefix
        ai_label = f"[{_time.strftime('%H:%M:%S')}] AI  › "
        self._print(ai_label, "#00ff88", newline=False)

        # Get vitals
        vitals = self.monitor.get_vitals_snapshot() if self.monitor else {}
        if self.monitor:
            res = self.monitor.res_monitor.get_snapshot() if hasattr(self.monitor, 'res_monitor') else {}
            vitals["res_access"] = res

        self._busy = True
        self.send_btn.setEnabled(False)
        self.send_btn.setText("⟳ ...")

        # Run in thread
        worker = _TokenWorker(self.ai, msg, vitals)
        worker.token_ready.connect(self._on_token)
        worker.done.connect(self._on_done)

        self._worker_thread = threading.Thread(
            target=worker.run, daemon=True, name="KHB-AIChat"
        )
        self._worker_thread.start()
        # Store worker ref to prevent GC
        self._current_worker = worker

    def _on_token(self, token: str):
        """Called for each streamed token."""
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#00ff88"))
        cursor.setCharFormat(fmt)
        cursor.insertText(token)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()

    def _on_done(self, full_response: str):
        self._print("\n" + "─" * 60, "#002233")
        self._busy = False
        self.send_btn.setEnabled(True)
        self.send_btn.setText("⏎ SEND")

    def _print(self, text: str, color: str = "#00eeff", newline: bool = True):
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text + ("\n" if newline else ""))
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()

    def _set_font_size(self, size_px: int):
        self.chat_display.setStyleSheet(f"""
            background-color: #00020a;
            color: #00eeff;
            border: 1px solid #003340;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: {size_px}px;
            selection-background-color: #002233;
        """)
