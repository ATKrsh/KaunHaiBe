"""
KaunHaiBe - Desktop Widget
captureME-style floating circle with multi-source glow:
  Grey  = idle
  Yellow = CPU spike
  Blue   = GPU spike
  Green  = HDD/SSD spike
  Red    = Input / File anomaly / USB error

Right-click → opens Dashboard
"""
import sys
import os
import math
import time
import threading

from PyQt5.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu, QAction,
    QVBoxLayout, QHBoxLayout, QSlider, QWidgetAction, QLabel
)
from PyQt5.QtCore import Qt, QPoint, QRectF, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QIcon, QPixmap, QCursor, QRadialGradient
)

APP_NAME = "KaunHaiBe"

try:
    import winreg
    _winreg_available = True
except ImportError:
    _winreg_available = False

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_startup(enable: bool):
    if not _winreg_available:
        return
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_ALL_ACCESS)
        if enable:
            exe = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass


def check_startup() -> bool:
    if not _winreg_available:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


class KaunHaiBe_Widget(QWidget):
    # Signals
    open_dashboard_signal = pyqtSignal()
    open_terminal_alert_signal = pyqtSignal()
    open_terminal_ai_signal = pyqtSignal()

    def __init__(self, monitor_engine=None):
        super().__init__()
        self.monitor = monitor_engine

        # Animation state
        self.breath_phase = 0.0
        self.current_glow_intensity = 0.0
        self.current_spike_source = "idle"
        self.current_glow_color = QColor(120, 120, 120)  # Grey idle
        self.current_icon_scale = 0.0
        self.spike_label_text = "IDLE"

        # Drag
        self.dragging = False
        self.drag_start_pos = QPoint()
        self.click_press_pos = QPoint()
        self.is_drag_moved = False

        # Config
        self.opacity_val = 0.92
        self.glow_opacity = 0.85
        self.glow_size_pct = 55
        self.widget_size_pct = 50
        self.always_on_top = True
        self.lock_position = False

        self._load_config()
        self._init_ui()

        # Animation timer
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(20)
        self.anim_timer.timeout.connect(self._animate)
        self.anim_timer.start()

        # Vitals poll timer
        self.vitals_timer = QTimer(self)
        self.vitals_timer.setInterval(500)
        self.vitals_timer.timeout.connect(self._poll_vitals)
        self.vitals_timer.start()

        self._create_tray()

    def _load_config(self):
        import json
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "widget_config.json")
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
            self.opacity_val = cfg.get("opacity", 0.92)
            self.glow_opacity = cfg.get("glow_opacity", 0.85)
            self.glow_size_pct = cfg.get("glow_size_pct", 55)
            self.widget_size_pct = cfg.get("widget_size_pct", 50)
            self.always_on_top = cfg.get("always_on_top", True)
            self.lock_position = cfg.get("lock_position", False)
            self._pos_x = cfg.get("pos_x", 100)
            self._pos_y = cfg.get("pos_y", 100)
        except Exception:
            self._pos_x = 100
            self._pos_y = 100

    def _save_config(self):
        import json
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "widget_config.json")
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        try:
            with open(cfg_path, "w") as f:
                json.dump({
                    "opacity": self.opacity_val,
                    "glow_opacity": self.glow_opacity,
                    "glow_size_pct": self.glow_size_pct,
                    "widget_size_pct": self.widget_size_pct,
                    "always_on_top": self.always_on_top,
                    "lock_position": self.lock_position,
                    "pos_x": self.pos().x(),
                    "pos_y": self.pos().y(),
                }, f, indent=2)
        except Exception:
            pass

    def _base_size(self):
        return int(40 + (120 * (self.widget_size_pct / 100.0)))

    def _init_ui(self):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setWindowTitle(APP_NAME)

        bs = self._base_size()
        sz = bs + 60
        self.setFixedSize(sz, sz)
        self.move(self._pos_x, self._pos_y)
        self.show()

    def _create_tray(self):
        # Tray icon
        px = QPixmap(32, 32)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 220, 0), 2))
        p.setBrush(QBrush(QColor(20, 20, 30)))
        p.drawEllipse(3, 3, 26, 26)
        p.setBrush(QBrush(QColor(255, 220, 0)))
        p.drawEllipse(12, 12, 8, 8)
        p.end()

        self.tray = QSystemTrayIcon(QIcon(px), self)
        self.tray.setToolTip("KaunHaiBe — System Lag Monitor")

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #12151c;
                color: #e0e4ee;
                border: 1px solid #2a3040;
                border-radius: 8px;
                padding: 6px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QMenu::item { padding: 6px 22px 6px 12px; border-radius: 4px; }
            QMenu::item:selected { background-color: #1e2535; color: #ffdc00; }
            QMenu::separator { height: 1px; background: #2a3040; margin: 4px 6px; }
        """)

        act_dash = QAction("📊  Open Dashboard", self)
        act_dash.triggered.connect(self.open_dashboard_signal.emit)
        menu.addAction(act_dash)

        act_term = QAction("🖥  Problem Terminal", self)
        act_term.triggered.connect(self.open_terminal_alert_signal.emit)
        menu.addAction(act_term)

        act_ai = QAction("🤖  AI Chat Terminal", self)
        act_ai.triggered.connect(self.open_terminal_ai_signal.emit)
        menu.addAction(act_ai)

        menu.addSeparator()

        act_top = QAction("Always on Top", self, checkable=True)
        act_top.setChecked(self.always_on_top)
        act_top.triggered.connect(self._toggle_always_on_top)
        menu.addAction(act_top)

        act_lock = QAction("Lock Position", self, checkable=True)
        act_lock.setChecked(self.lock_position)
        act_lock.triggered.connect(lambda c: setattr(self, 'lock_position', c) or self._save_config())
        menu.addAction(act_lock)

        act_startup = QAction("Start with Windows", self, checkable=True)
        act_startup.setChecked(check_startup())
        act_startup.triggered.connect(lambda c: set_startup(c))
        menu.addAction(act_startup)

        menu.addSeparator()

        # Opacity slider
        def _make_slider(label, attr, min_v, max_v, current, fmt, on_change):
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(12, 3, 12, 3)
            lbl_title = QLabel(label)
            lbl_title.setStyleSheet("color:#9ca3af;font-size:11px;font-weight:bold;")
            lbl_title.setFixedWidth(85)
            lbl_val = QLabel(fmt(current))
            lbl_val.setStyleSheet("color:#ffdc00;font-size:11px;font-weight:bold;")
            lbl_val.setFixedWidth(36)
            sld = QSlider(Qt.Horizontal)
            sld.setRange(min_v, max_v)
            sld.setValue(current)
            sld.setFixedWidth(110)
            sld.setStyleSheet("""
                QSlider::groove:horizontal{height:4px;background:#2a3040;border-radius:2px;}
                QSlider::sub-page:horizontal{background:#ffdc00;border-radius:2px;}
                QSlider::handle:horizontal{background:#fff;width:12px;height:12px;margin:-4px 0;border-radius:6px;}
            """)
            def _changed(v):
                lbl_val.setText(fmt(v))
                on_change(v)
            sld.valueChanged.connect(_changed)
            lay.addWidget(lbl_title)
            lay.addWidget(sld)
            lay.addWidget(lbl_val)
            wa = QWidgetAction(self)
            wa.setDefaultWidget(w)
            return wa

        menu.addAction(_make_slider("App Opacity:", "opacity_val", 20, 100,
            int(self.opacity_val * 100), lambda v: f"{v}%",
            lambda v: setattr(self, 'opacity_val', v/100) or self._save_config() or self.update()))

        menu.addAction(_make_slider("Glow Opacity:", "glow_opacity", 0, 100,
            int(self.glow_opacity * 100), lambda v: f"{v}%",
            lambda v: setattr(self, 'glow_opacity', v/100) or self._save_config()))

        menu.addAction(_make_slider("Glow Size:", "glow_size_pct", 0, 100,
            self.glow_size_pct, lambda v: f"{v}%",
            lambda v: setattr(self, 'glow_size_pct', v) or self._save_config()))

        menu.addAction(_make_slider("Widget Size:", "widget_size_pct", 0, 100,
            self.widget_size_pct, lambda v: f"{v}%",
            lambda v: (setattr(self, 'widget_size_pct', v),
                       self.setFixedSize(self._base_size()+180, self._base_size()+180),
                       self._save_config())))

        menu.addSeparator()

        act_exit = QAction("Exit KaunHaiBe", self)
        act_exit.triggered.connect(QApplication.quit)
        menu.addAction(act_exit)

        self.tray.setContextMenu(menu)
        self.tray.show()
        self.tray.activated.connect(self._tray_activated)

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.open_dashboard_signal.emit()

    def _toggle_always_on_top(self, checked):
        self.always_on_top = checked
        flags = Qt.FramelessWindowHint | Qt.Tool
        if checked:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self._save_config()

    def _poll_vitals(self):
        """Pull latest spike state from monitor engine."""
        if not self.monitor:
            return
        source = self.monitor.current_spike_source
        intensity = self.monitor.current_spike_intensity
        rgb = self.monitor.current_glow_color

        self.current_spike_source = source
        self.current_glow_color = QColor(*rgb)

        # Animate intensity toward target
        if intensity > self.current_glow_intensity:
            self.current_glow_intensity = intensity
        else:
            self.current_glow_intensity += (intensity - self.current_glow_intensity) * 0.35

        labels = {"cpu": "CPU", "gpu": "GPU", "disk": "DISK", "input": "INPUT", "idle": "STABLE"}
        self.spike_label_text = labels.get(source, source.upper())

    def _animate(self):
        self.breath_phase += 0.035
        cur_pos = QCursor.pos()
        w_center = self.mapToGlobal(QPoint(self.width() // 2, self.height() // 2))
        dx = cur_pos.x() - w_center.x()
        dy = cur_pos.y() - w_center.y()
        dist = math.sqrt(dx*dx + dy*dy)
        proximity = max(0.0, 1.0 - dist / 300.0)
        sine = (math.sin(self.breath_phase) + 1.0) / 2.0
        target_scale = sine * 3.0 + proximity * 10.0
        self.current_icon_scale = self.current_icon_scale + (target_scale - self.current_icon_scale) * 0.2
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        bs = self._base_size()
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        d_size = bs + self.current_icon_scale
        rect = QRectF(cx - d_size/2, cy - d_size/2, d_size, d_size)

        intensity = min(1.0, max(0.0, self.current_glow_intensity))
        gc = self.current_glow_color
        alpha = int((55 + 190 * intensity) * self.glow_opacity)
        alpha = min(245, max(0, alpha))

        sz_scale = self.glow_size_pct / 100.0
        sine_val = (math.sin(self.breath_phase) + 1.0) / 2.0
        glow_ext = 5 + 40 * sz_scale + intensity * (5 + 55 * sz_scale)
        glow_r = d_size / 2 + glow_ext

        glow_color = QColor(gc.red(), gc.green(), gc.blue(), alpha)
        outer_color = QColor(gc.red(), gc.green(), gc.blue(), int(alpha * 0.4))

        # Outer ambient aura
        ro = QRadialGradient(cx, cy, glow_r + 18)
        ro.setColorAt(0.0, outer_color)
        ro.setColorAt(0.6, QColor(gc.red(), gc.green(), gc.blue(), int(alpha * 0.12)))
        ro.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(ro))
        p.setPen(Qt.NoPen)
        r = glow_r + 18
        p.drawEllipse(QRectF(cx-r, cy-r, r*2, r*2))

        # Inner core glow
        ri = QRadialGradient(cx, cy, glow_r)
        ri.setColorAt(0.0, glow_color)
        ri.setColorAt(0.65, QColor(gc.red(), gc.green(), gc.blue(), int(alpha * 0.4)))
        ri.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(ri))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx-glow_r, cy-glow_r, glow_r*2, glow_r*2))

        # Main body
        body_alpha = int(215 * self.opacity_val)
        border_alpha = int((50 + 180 * intensity) * self.opacity_val)
        p.setBrush(QBrush(QColor(14, 17, 26, body_alpha)))
        p.setPen(QPen(QColor(255, 255, 255, border_alpha), 1.6))
        p.drawEllipse(rect)

        # Center ring
        cr = d_size * 0.18
        cr_rect = QRectF(cx-cr, cy-cr, cr*2, cr*2)
        fill_c = QColor(gc.red(), gc.green(), gc.blue(), int(180 * self.opacity_val))
        p.setBrush(QBrush(QColor(25, 30, 45, int(200 * self.opacity_val))))
        p.setPen(QPen(fill_c, 2))
        p.drawEllipse(cr_rect)

        # Center dot (pulsing)
        dot_r = cr * 0.38
        dot_alpha = int((140 + 110 * intensity) * self.opacity_val)
        dot_c = QColor(gc.red(), gc.green(), gc.blue(), dot_alpha)
        p.setBrush(QBrush(dot_c))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx-dot_r, cy-dot_r, dot_r*2, dot_r*2))

        # Status label
        label_y = cy + d_size / 2 + 14
        p.setPen(QColor(gc.red(), gc.green(), gc.blue(), int(200 * self.opacity_val)))
        font = p.font()
        font.setFamily("Consolas")
        font.setPointSize(7)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(cx-50, label_y, 100, 16), Qt.AlignCenter, self.spike_label_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.lock_position:
            self.dragging = True
            self.drag_start_pos = event.globalPos() - self.frameGeometry().topLeft()
            self.click_press_pos = event.globalPos()
            self.is_drag_moved = False
        elif event.button() == Qt.RightButton:
            self.open_dashboard_signal.emit()

    def mouseMoveEvent(self, event):
        if self.dragging and (event.buttons() & Qt.LeftButton):
            if (event.globalPos() - self.click_press_pos).manhattanLength() > 4:
                self.is_drag_moved = True
            self.move(event.globalPos() - self.drag_start_pos)
            self._save_config()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            if not self.is_drag_moved:
                self.open_dashboard_signal.emit()
