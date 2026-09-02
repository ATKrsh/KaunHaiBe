"""
KaunHaiBe - Main Entry Point
"""
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

# Ensure data dirs exist
for d in ["data", "logs"]:
    os.makedirs(os.path.join(os.path.dirname(__file__), d), exist_ok=True)

# Create empty __init__ files for package imports (only when running as raw source script)
if not getattr(sys, 'frozen', False):
    for pkg in ["core", "core/collectors", "ai", "ui"]:
        init_path = os.path.join(os.path.dirname(__file__), pkg, "__init__.py")
        try:
            if not os.path.exists(init_path):
                open(init_path, "w").close()
        except Exception:
            pass


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("KaunHaiBe")

    # Start monitor engine
    from core.monitor import MonitorEngine
    monitor = MonitorEngine()

    # Start AI engine
    from ai.engine import AIEngine
    ai = AIEngine()

    # Create UI components (lazy imports after app created)
    from ui.widget import KaunHaiBe_Widget
    from ui.dashboard import Dashboard
    from ui.terminal_alert import TerminalAlert
    from ui.terminal_ai import TerminalAI

    dashboard = Dashboard(monitor_engine=monitor, ai_engine=ai)
    widget   = KaunHaiBe_Widget(monitor_engine=monitor)
    term_alert = dashboard.term_alert_widget
    term_ai    = dashboard.term_ai_widget

    # Wire alert callbacks → terminal
    def _on_alert(msg):
        term_alert.push_alert(msg)

    monitor.on_alert = _on_alert

    # Wire widget signals
    widget.open_dashboard_signal.connect(lambda: (dashboard.show(), dashboard.raise_()))
    widget.open_terminal_alert_signal.connect(lambda: (dashboard.show(), dashboard.tabs.setCurrentIndex(16), dashboard.raise_()))
    widget.open_terminal_ai_signal.connect(lambda: (dashboard.show(), dashboard.tabs.setCurrentIndex(17), dashboard.raise_()))

    # Start monitoring
    monitor.start()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
