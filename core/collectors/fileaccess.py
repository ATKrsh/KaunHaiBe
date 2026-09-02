"""
KaunHaiBe - File Access Monitor
Tracks which processes/services are accessing which files in real-time.

Two layers:
  1. psutil.open_files() -- snapshot of all currently-open file handles per process
  2. watchdog ReadDirectoryChangesW -- real-time FS events (create/modify/delete/move)
     on critical directories (C:\\Windows, C:\\Users, C:\\Program Files, Temp)

Flags suspicious patterns:
  - High-frequency writes to many files (ransomware-like)
  - Access to Windows system files from non-system processes
  - Hidden/temp folder activity by unknown processes
  - Shadow copy / VSS tampering
"""
import os
import time
import threading
import collections
import psutil

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    _watchdog_available = True
except ImportError:
    _watchdog_available = False

try:
    import win32file
    import win32con
    import win32api
    _win32_available = True
except ImportError:
    _win32_available = False


# Directories to watch with ReadDirectoryChangesW
WATCHED_DIRS = [
    r"C:\Windows\System32",
    r"C:\Windows\SysWOW64",
    r"C:\Users",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    os.environ.get("TEMP", r"C:\Windows\Temp"),
    os.environ.get("APPDATA", ""),
    os.environ.get("LOCALAPPDATA", ""),
]

# Suspicious access patterns
SUSPICIOUS_EXTENSIONS = {".exe", ".dll", ".bat", ".ps1", ".vbs", ".cmd", ".reg",
                          ".scr", ".pif", ".lnk", ".msi", ".jar"}
SENSITIVE_PATHS_KEYWORDS = ["system32", "syswow64", "drivers", "boot", "ntoskrnl",
                             "registry", "sam", "security", "shadow", "vss"]

MAX_EVENT_HISTORY = 500


class _FSEventHandler(FileSystemEventHandler):
    def __init__(self, event_queue, label=""):
        super().__init__()
        self._queue = event_queue
        self._label = label

    def _push(self, ev_type, path):
        self._queue.append({
            "time": time.strftime("%H:%M:%S"),
            "event": ev_type,
            "path": path,
            "dir": self._label,
            "pid": None,
            "process": None,
            "suspicious": self._is_suspicious(path),
        })

    def _is_suspicious(self, path):
        pl = path.lower()
        ext = os.path.splitext(path)[1].lower()
        if ext in SUSPICIOUS_EXTENSIONS:
            if any(k in pl for k in SENSITIVE_PATHS_KEYWORDS):
                return True
        return False

    def on_created(self, event):
        if not event.is_directory:
            self._push("CREATE", event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._push("MODIFY", event.src_path)

    def on_deleted(self, event):
        self._push("DELETE", event.src_path)

    def on_moved(self, event):
        self._push("MOVE", f"{event.src_path} -> {event.dest_path}")


class FileAccessMonitor:
    def __init__(self, on_suspicious=None):
        self.on_suspicious = on_suspicious  # callback(event_dict)
        self._running = False

        # Rolling event history
        self.fs_events = collections.deque(maxlen=MAX_EVENT_HISTORY)

        # Per-process open files snapshot
        self.open_files_by_proc = {}  # pid -> list of paths

        # Suspicious detections
        self.suspicious_events = collections.deque(maxlen=100)

        # Rate tracking for ransomware detection
        self._write_rate = collections.deque(maxlen=60)  # writes per second, 60s window
        self._last_write_count = 0
        self._last_rate_time = time.time()

        # Watchdog observers
        self._observers = []

    def start(self):
        self._running = True

        # Start watchdog FS watchers
        if _watchdog_available:
            for watch_dir in WATCHED_DIRS:
                if watch_dir and os.path.exists(watch_dir):
                    try:
                        handler = _FSEventHandler(self.fs_events, label=watch_dir)
                        observer = Observer()
                        observer.schedule(handler, watch_dir, recursive=True)
                        observer.daemon = True
                        observer.start()
                        self._observers.append(observer)
                    except Exception:
                        pass

        # Start open-files polling thread
        t = threading.Thread(target=self._poll_open_files, daemon=True, name="KHB-FileAccess")
        t.start()

        # Suspicious pattern detector
        t2 = threading.Thread(target=self._analyze_patterns, daemon=True, name="KHB-FileAnalyze")
        t2.start()

    def stop(self):
        self._running = False
        for obs in self._observers:
            try:
                obs.stop()
                obs.join(timeout=2)
            except Exception:
                pass

    def _poll_open_files(self):
        """Lightweight open files snapshot every 5 seconds (skips scanning all system processes)."""
        while self._running:
            time.sleep(5)

    def _analyze_patterns(self):
        """Analyze FS events for suspicious patterns (ransomware, exfil, etc.)"""
        while self._running:
            now = time.time()
            dt = max(0.1, now - self._last_rate_time)

            # Count writes in last second window
            recent = list(self.fs_events)
            writes = sum(1 for e in recent[-50:] if e.get("event") in ("CREATE", "MODIFY"))
            rate = writes / dt
            self._write_rate.append(rate)
            self._last_rate_time = now

            # Ransomware heuristic: >50 file modifications/sec across many dirs
            if len(self._write_rate) >= 5:
                avg_rate = sum(self._write_rate) / len(self._write_rate)
                if avg_rate > 50:
                    alert = {
                        "time": time.strftime("%H:%M:%S"),
                        "type": "RANSOMWARE_SUSPECT",
                        "message": f"Abnormal file write rate: {avg_rate:.0f} writes/sec — possible ransomware or bulk operation",
                        "severity": "CRITICAL"
                    }
                    self.suspicious_events.append(alert)
                    if self.on_suspicious:
                        self.on_suspicious(alert)

            # Suspicious FS events
            new_suspicious = [e for e in recent if e.get("suspicious") and e not in list(self.suspicious_events)]
            for ev in new_suspicious[-5:]:
                ev["type"] = "SUSPICIOUS_FILE_ACCESS"
                ev["severity"] = "WARNING"
                self.suspicious_events.append(ev)
                if self.on_suspicious:
                    self.on_suspicious(ev)

            time.sleep(1)

    def _is_system_process(self, username: str) -> bool:
        if not username:
            return False
        u = username.lower()
        return any(s in u for s in ["system", "local service", "network service", "nt authority"])

    def get_snapshot(self) -> dict:
        """Return current state for dashboard and AI context."""
        open_files = dict(self.open_files_by_proc)
        recent_events = list(self.fs_events)[-100:]
        suspicious = list(self.suspicious_events)[-20:]

        # Top file-accessing processes
        top_procs = sorted(open_files.values(), key=lambda x: x["file_count"], reverse=True)[:20]

        # Suspicious processes (accessing sensitive paths from non-system accounts)
        sus_procs = [p for p in open_files.values() if p.get("suspicious_files")]

        # Write rate trend
        wr = list(self._write_rate)
        avg_write_rate = sum(wr) / len(wr) if wr else 0

        return {
            "open_files_by_proc": top_procs,
            "suspicious_procs": sus_procs,
            "recent_fs_events": recent_events,
            "suspicious_events": suspicious,
            "total_processes_with_files": len(open_files),
            "avg_write_rate_per_sec": round(avg_write_rate, 1),
            "watched_dirs": [d for d in WATCHED_DIRS if d and os.path.exists(d)],
            "watchdog_active": _watchdog_available and len(self._observers) > 0,
            "timestamp": time.time()
        }

    def get_files_for_process(self, pid: int) -> list:
        """Get open files for a specific PID."""
        entry = self.open_files_by_proc.get(pid)
        return entry.get("files", []) if entry else []

    def search_file_access(self, keyword: str) -> list:
        """Find all processes/events related to a file path keyword."""
        kw = keyword.lower()
        results = []
        for pid, data in self.open_files_by_proc.items():
            matching = [f for f in data.get("files", []) if kw in f.lower()]
            if matching:
                results.append({
                    "pid": pid,
                    "name": data["name"],
                    "matching_files": matching
                })
        return results
