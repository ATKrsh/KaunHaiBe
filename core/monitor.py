"""
KaunHaiBe - Central Monitor Engine
Runs all collectors in background threads, maintains rolling history,
detects spikes, emits signals for UI.
"""
import threading
import time
import collections
import json
import os

from core.collectors import cpu, gpu, disk, motherboard, usb
from core.collectors.system import (
    collect_services, collect_processes, collect_eventlog,
    collect_apps, collect_temp, collect_registry,
    collect_threads, collect_kernel, collect_interrupts
)
from core.collectors.fileaccess import FileAccessMonitor
from core.collectors.resaccess import ResourceAccessMonitor


HISTORY_SIZE = 300  # 300 samples @ ~1s = 5 min rolling window
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
BASELINE_FILE = os.path.join(DATA_DIR, "baseline.json")
EVENT_LOG_FILE = os.path.join(DATA_DIR, "events.jsonl")

# Spike thresholds (can be overridden by learned baseline)
DEFAULT_THRESHOLDS = {
    "cpu_usage": 85,
    "gpu_usage": 90,
    "disk_read_mbps": 200,
    "disk_write_mbps": 200,
    "ram_usage": 90,
    "interrupt_per_sec": 50000,
    "ctx_switches_delta": 200000,
    "input_error_count": 1,
}

# Spike colors for widget glow
SPIKE_COLORS = {
    "cpu":   (255, 220, 0),    # Yellow
    "gpu":   (0, 140, 255),    # Blue
    "disk":  (0, 220, 80),     # Green
    "input": (255, 40, 40),    # Red
    "idle":  (120, 120, 120),  # Grey
}


class MonitorEngine:
    def __init__(self, on_update=None, on_spike=None, on_alert=None):
        self.on_update = on_update   # callback(vitals_dict)
        self.on_spike  = on_spike    # callback(source, intensity, color)
        self.on_alert  = on_alert    # callback(alert_text)

        self._running = False
        self._lock = threading.Lock()

        # Rolling history
        self.history = {
            "cpu": collections.deque(maxlen=HISTORY_SIZE),
            "gpu": collections.deque(maxlen=HISTORY_SIZE),
            "disk": collections.deque(maxlen=HISTORY_SIZE),
            "ram": collections.deque(maxlen=HISTORY_SIZE),
            "interrupts": collections.deque(maxlen=HISTORY_SIZE),
        }

        # Latest vitals snapshot
        self.vitals = {}

        # Spike state
        self.current_spike_source = "idle"
        self.current_spike_intensity = 0.0
        self.current_glow_color = SPIKE_COLORS["idle"]

        # Learned baseline
        self.baseline = self._load_baseline()
        self.thresholds = {**DEFAULT_THRESHOLDS, **self.baseline.get("thresholds", {})}

        # Slow collectors (run less often)
        self._slow_vitals = {}
        self._slow_counter = 0
        self._apps_cache = None
        self._apps_last = 0

        # File access monitor
        self.file_monitor = FileAccessMonitor(on_suspicious=self._on_file_suspicious)

        # Resource access monitor (per-process: net/disk/cpu/gpu/sec events)
        self.res_monitor = ResourceAccessMonitor(on_alert=self._on_res_alert)

        self._threads = []

    def start(self):
        self._running = True

        # Perform quick initial pass of slow vitals so USB, EventLog, Services populate immediately
        try:
            initial_usb = usb.collect()
            initial_evlog = collect_eventlog(max_entries=30)
            initial_svc = collect_services()
            with self._lock:
                self._slow_vitals = {
                    "services": initial_svc,
                    "usb": initial_usb,
                    "eventlog": initial_evlog,
                    "temp_folders": {},
                    "registry": {},
                    "apps": {"apps": []},
                }
                for k, val in self._slow_vitals.items():
                    self.vitals[k] = val
        except Exception:
            pass

        # Main fast loop
        t = threading.Thread(target=self._fast_loop, daemon=True, name="KHB-FastLoop")
        t.start()
        self._threads.append(t)

        # Slow loop (every 30s)
        t2 = threading.Thread(target=self._slow_loop, daemon=True, name="KHB-SlowLoop")
        t2.start()
        self._threads.append(t2)

        # Baseline learner (every 5 min)
        t3 = threading.Thread(target=self._baseline_loop, daemon=True, name="KHB-Baseline")
        t3.start()
        self._threads.append(t3)

        # File access monitor (own threads internally)
        self.file_monitor.start()

        # Resource access monitor (own threads internally)
        self.res_monitor.start()

    def stop(self):
        self._running = False
        self.file_monitor.stop()
        self.res_monitor.stop()

    def _fast_loop(self):
        """~1s interval: CPU, GPU, Disk, RAM, Processes, Interrupts"""
        while self._running:
            t0 = time.time()
            try:
                c = cpu.collect()
                g = gpu.collect()
                d = disk.collect()
                mb = motherboard.collect()
                proc = collect_processes()
                intr = collect_interrupts()
                kern = collect_kernel()
                thrd = collect_threads()

                fa  = self.file_monitor.get_snapshot()
                res = self.res_monitor.get_snapshot()

                with self._lock:
                    self.vitals["cpu"]         = c
                    self.vitals["gpu"]         = g
                    self.vitals["disk"]        = d
                    self.vitals["motherboard"] = mb
                    self.vitals["processes"]   = proc
                    self.vitals["interrupts"]  = intr
                    self.vitals["kernel"]      = kern
                    self.vitals["threads"]     = thrd
                    self.vitals["file_access"] = fa
                    self.vitals["res_access"]  = res
                    for k, val in self._slow_vitals.items():
                        self.vitals[k] = val

                    # Update history
                    self.history["cpu"].append(c.get("usage_total", 0) or 0)
                    self.history["gpu"].append(g.get("usage_pct", 0) or 0)
                    r_mb = d.get("max_read_mbps") or 0
                    w_mb = d.get("max_write_mbps") or 0
                    self.history["disk"].append(max(r_mb, w_mb))
                    self.history["ram"].append(mb.get("ram", {}).get("usage_pct", 0) if mb.get("ram") else 0)
                    self.history["interrupts"].append(intr.get("interrupts_per_sec", 0) or 0)

                # Spike detection
                self._detect_spikes(c, g, d, mb, intr)

                if self.on_update:
                    self.on_update(dict(self.vitals))

            except Exception as e:
                import traceback
                print(f"[FASTLOOP EXCEPTION] {e}", file=sys.stderr)
                traceback.print_exc()
                self._log_event("error", f"FastLoop error: {e}")

            elapsed = time.time() - t0
            sleep_t = max(0.05, 1.0 - elapsed)
            time.sleep(sleep_t)

    def _slow_loop(self):
        """30s interval: services, USB, event log, temp, registry, threads"""
        while self._running:
            try:
                svc = collect_services()
                usb_data = usb.collect()
                evlog = collect_eventlog(max_entries=30)
                tmp = collect_temp()
                reg = collect_registry()

                # Apps cached (refresh every 5 min)
                now = time.time()
                if self._apps_cache is None or now - self._apps_last > 300:
                    self._apps_cache = collect_apps()
                    self._apps_last = now

                with self._lock:
                    self._slow_vitals = {
                        "services": svc,
                        "usb": usb_data,
                        "eventlog": evlog,
                        "temp_folders": tmp,
                        "registry": reg,
                        "apps": self._apps_cache,
                    }
                    for k, val in self._slow_vitals.items():
                        self.vitals[k] = val

                # Check USB/input errors
                if usb_data.get("error_device_count", 0) > 0:
                    self._emit_spike("input", 0.7)
                    self._log_event("warning", f"USB/Input device errors: {usb_data['error_device_count']}")

                # Check event log for critical errors
                for ev in evlog.get("entries", []):
                    if ev.get("type") == "Error":
                        self._log_event("system_error", ev.get("message", "")[:100], ev)

            except Exception as e:
                self._log_event("error", f"SlowLoop error: {e}")

            time.sleep(30)

    def _baseline_loop(self):
        """Every 5 min: update learned baseline from history"""
        time.sleep(60)  # Wait 1 min before first baseline
        while self._running:
            try:
                self._update_baseline()
            except Exception as e:
                pass
            time.sleep(300)

    def _on_file_suspicious(self, event: dict):
        """Callback from FileAccessMonitor when suspicious file activity detected."""
        msg = event.get("message") or f"Suspicious file access: {event.get('path','?')} ({event.get('event','?')})"
        self._log_event("file_suspicious", msg, event)
        if self.on_alert:
            self.on_alert(f"[FILE] {msg}")
        # Escalate as input/system spike if critical
        if event.get("severity") == "CRITICAL":
            self._emit_spike("input", 0.9, (255, 40, 40))

    def _on_res_alert(self, msg: str):
        """Callback from ResourceAccessMonitor for high-risk process activity."""
        self._log_event("resource_alert", msg)
        if self.on_alert:
            self.on_alert(msg)
        # Risk alerts affecting credentials/permissions spike as red
        if any(k in msg for k in ["CREDENTIAL", "PERMISSION", "OWNERSHIP", "SEC:", "RISK:8", "RISK:9", "RISK:10"]):
            self._emit_spike("input", 0.85, (255, 40, 40))

    def _detect_spikes(self, c, g, d, mb, intr):
        cpu_val  = c.get("usage_total", 0) or 0
        gpu_val  = g.get("usage_pct", 0) or 0
        r_mb     = d.get("max_read_mbps") or 0
        w_mb     = d.get("max_write_mbps") or 0
        disk_val = max(r_mb, w_mb)
        ram_val  = mb.get("ram", {}).get("usage_pct", 0) if mb.get("ram") else 0
        intr_val = intr.get("interrupts_per_sec", 0) or 0

        spikes = []

        if cpu_val > self.thresholds["cpu_usage"]:
            intensity = min(1.0, (cpu_val - self.thresholds["cpu_usage"]) / (100 - self.thresholds["cpu_usage"]))
            spikes.append(("cpu", intensity, SPIKE_COLORS["cpu"]))
            self._log_event("spike", f"CPU spike: {cpu_val:.1f}%")

        if gpu_val > self.thresholds["gpu_usage"]:
            intensity = min(1.0, (gpu_val - self.thresholds["gpu_usage"]) / (100 - self.thresholds["gpu_usage"]))
            spikes.append(("gpu", intensity, SPIKE_COLORS["gpu"]))
            self._log_event("spike", f"GPU spike: {gpu_val:.1f}%")

        if disk_val > self.thresholds["disk_read_mbps"]:
            intensity = min(1.0, disk_val / (self.thresholds["disk_read_mbps"] * 2))
            spikes.append(("disk", intensity, SPIKE_COLORS["disk"]))

        if intr_val > self.thresholds["interrupt_per_sec"]:
            intensity = min(1.0, intr_val / (self.thresholds["interrupt_per_sec"] * 2))
            spikes.append(("input", intensity, SPIKE_COLORS["input"]))

        if spikes:
            # Dominant spike = highest intensity
            spikes.sort(key=lambda x: x[1], reverse=True)
            source, intensity, color = spikes[0]
            self._emit_spike(source, intensity, color)
        else:
            # Smooth decay back to idle
            self.current_spike_intensity = max(0.0, self.current_spike_intensity - 0.05)
            if self.current_spike_intensity < 0.05:
                self.current_spike_source = "idle"
                self.current_glow_color = SPIKE_COLORS["idle"]

    def _emit_spike(self, source, intensity, color=None):
        self.current_spike_source = source
        self.current_spike_intensity = intensity
        self.current_glow_color = color or SPIKE_COLORS.get(source, SPIKE_COLORS["idle"])
        if self.on_spike:
            self.on_spike(source, intensity, self.current_glow_color)

    def _log_event(self, event_type, message, extra=None):
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "type": event_type,
            "message": message,
        }
        if extra:
            entry["extra"] = extra
        try:
            with open(EVENT_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass
        if self.on_alert and event_type in ("spike", "warning", "system_error"):
            self.on_alert(f"[{event_type.upper()}] {message}")

    def _update_baseline(self):
        with self._lock:
            h = dict(self.history)
        if len(h["cpu"]) < 30:
            return

        def percentile(data, p):
            s = sorted(data)
            idx = int(len(s) * p / 100)
            return s[min(idx, len(s)-1)]

        cpu_list  = list(h["cpu"])
        gpu_list  = list(h["gpu"])
        disk_list = list(h["disk"])
        ram_list  = list(h["ram"])

        # Learn thresholds as 95th percentile + 10% headroom
        new_thresh = {
            "cpu_usage":      min(95, max(70, percentile(cpu_list, 95) * 1.10)),
            "gpu_usage":      min(95, max(75, percentile(gpu_list, 95) * 1.10)),
            "disk_read_mbps": min(500, max(100, percentile(disk_list, 95) * 1.20)),
            "disk_write_mbps":min(500, max(100, percentile(disk_list, 95) * 1.20)),
        }

        baseline_data = {
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "thresholds": new_thresh,
            "avg_cpu": round(sum(cpu_list)/len(cpu_list), 2),
            "avg_gpu": round(sum(gpu_list)/len(gpu_list), 2),
            "avg_disk": round(sum(disk_list)/len(disk_list), 2),
            "avg_ram": round(sum(ram_list)/len(ram_list), 2) if ram_list else 0,
        }
        self.baseline = baseline_data
        self.thresholds = {**DEFAULT_THRESHOLDS, **new_thresh}

        try:
            with open(BASELINE_FILE, "w") as f:
                json.dump(baseline_data, f, indent=2)
        except Exception:
            pass

    def _load_baseline(self):
        try:
            if os.path.exists(BASELINE_FILE):
                with open(BASELINE_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def get_vitals_snapshot(self):
        with self._lock:
            return dict(self.vitals)

    def get_history(self):
        with self._lock:
            return {k: list(v) for k, v in self.history.items()}

    def get_recent_events(self, n=100):
        events = []
        try:
            with open(EVENT_LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines[-n:]):
                try:
                    events.append(json.loads(line.strip()))
                except Exception:
                    pass
        except Exception:
            pass
        return events
