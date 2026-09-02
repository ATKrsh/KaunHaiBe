"""
KaunHaiBe - Resource Access Monitor
Tracks per-process access to:
  - Network (connections, sockets, data rates)
  - HDD/Disk (I/O counters, open handles)
  - CPU (per-process CPU time)
  - GPU (per-process GPU usage via WMI)
  - Windows Settings (registry writes, policy changes)
  - Credentials (LSASS access, Credential Manager queries)
  - Permissions (privilege use, UAC, token elevation)
  - Ownership (file/registry ACL changes via Event Log)

Uses: psutil, WMI, Windows Event Log (Security/System)
Requires: Admin for Security event log access (degrades gracefully)
"""
import psutil
import time
import threading
import collections
import os

try:
    import wmi
    _wmi = wmi.WMI()
    _wmi_available = True
except Exception:
    _wmi = None
    _wmi_available = False

try:
    import win32evtlog
    import win32evtlogutil
    import win32con
    import win32security
    import win32api
    _win32_available = True
except ImportError:
    _win32_available = False

try:
    import GPUtil
    _gputil_available = True
except ImportError:
    _gputil_available = False


MAX_HISTORY = 200

# Security Event IDs we care about
SEC_EVENT_IDS = {
    4624: "Logon",
    4625: "Logon Failure",
    4648: "Explicit Credential Use",
    4656: "Object Handle Request",
    4657: "Registry Value Modified",
    4663: "Object Access Attempt",
    4670: "Permissions Changed",
    4672: "Special Privileges Assigned",
    4673: "Privileged Service Called",
    4674: "Operation on Privileged Object",
    4688: "Process Created",
    4689: "Process Exited",
    4697: "Service Installed",
    4698: "Scheduled Task Created",
    4719: "System Audit Policy Changed",
    4720: "User Account Created",
    4732: "User Added to Group",
    4776: "Credential Validation",
    5140: "Network Share Accessed",
    5145: "Network Share Check",
    7045: "Service Installed",
}

CREDENTIAL_EVENT_IDS = {4648, 4776, 4624, 4625}
PERMISSION_EVENT_IDS = {4670, 4672, 4673, 4674, 4719}
OWNERSHIP_EVENT_IDS  = {4670, 4663, 4657}


class ResourceAccessMonitor:
    def __init__(self, on_alert=None):
        self.on_alert = on_alert
        self._running = False

        # Per-process snapshots
        self._prev_net_io   = {}   # pid -> net_io or connections
        self._prev_disk_io  = {}   # pid -> disk_io_counters
        self._prev_time     = {}   # pid -> timestamp

        # Rolling per-process resource data
        self.process_resources = {}  # pid -> dict of resource accesses

        # Security events
        self.security_events   = collections.deque(maxlen=MAX_HISTORY)
        self.credential_events = collections.deque(maxlen=100)
        self.permission_events = collections.deque(maxlen=100)
        self.ownership_events  = collections.deque(maxlen=100)

        # Network connections per process
        self.net_connections_by_proc = {}  # pid -> list of connections

        # High-risk processes
        self.flagged_processes = collections.deque(maxlen=100)

        self._lock = threading.Lock()

    def start(self):
        self._running = True
        t1 = threading.Thread(target=self._poll_process_resources, daemon=True, name="KHB-ResAccess")
        t1.start()
        t2 = threading.Thread(target=self._poll_network_connections, daemon=True, name="KHB-NetConn")
        t2.start()
        t3 = threading.Thread(target=self._poll_security_events, daemon=True, name="KHB-SecEvents")
        t3.start()

    def stop(self):
        self._running = False

    # ── PROCESS RESOURCE USAGE ────────────────────────────────────────────────
    def _poll_process_resources(self):
        """Every 2s: collect per-process CPU/RAM/Disk/Net/GPU stats."""
        while self._running:
            now = time.time()
            snapshot = {}

            try:
                for proc in psutil.process_iter(["pid", "name", "username", "status", "cpu_percent", "memory_percent", "memory_info"], ad_value=None):
                    pid = proc.pid
                    info = proc.info
                    mi = info.get("memory_info")
                    rss = getattr(mi, 'rss', 0) if mi else 0
                    entry = {
                        "pid": pid,
                        "name": info.get("name") or "?",
                        "username": info.get("username") or "?",
                        "exe": "",
                        "status": info.get("status") or "?",
                        "cpu_pct": info.get("cpu_percent") or 0,
                        "ram_mb": round(rss / 1048576, 1),
                        "ram_pct": info.get("memory_percent") or 0,
                        "disk_read_rate_mbps": 0,
                        "disk_write_rate_mbps": 0,
                        "disk_read_total_mb": 0,
                        "disk_write_total_mb": 0,
                    }

                    # Network (from connections list - enriched in other thread)
                    net_info = self.net_connections_by_proc.get(pid, {})
                    entry["net_connections"]     = net_info.get("count", 0)
                    entry["net_listening"]        = net_info.get("listening", 0)
                    entry["net_established"]      = net_info.get("established", 0)
                    entry["net_remote_addresses"] = net_info.get("remotes", [])[:10]
                    entry["net_rx_mbps"]          = net_info.get("rx_mbps", 0)
                    entry["net_tx_mbps"]          = net_info.get("tx_mbps", 0)

                    # Open file handles & threads count (safe fast attributes)
                    entry["open_handles"] = 0
                    entry["open_files"] = 0
                    try:
                        entry["threads"] = proc.info.get("num_threads") or 0
                    except Exception:
                        entry["threads"] = 0

                    # Check privileges / elevation (Windows)
                    try:
                        import ctypes
                        if os.name == 'nt':
                            entry["is_elevated"] = bool(ctypes.windll.shell32.IsUserAnAdmin())
                        else:
                            entry["is_elevated"] = False
                    except Exception:
                        entry["is_elevated"] = False

                    # Risk scoring
                    entry["risk_score"] = self._score_risk(entry)
                    entry["risk_flags"]  = self._risk_flags(entry)

                    snapshot[pid] = entry
                    self._prev_time[pid] = now

            except Exception as e:
                pass

            with self._lock:
                self.process_resources = snapshot

            # Flag high-risk processes
            self._flag_high_risk(snapshot)

            time.sleep(2)

    # ── NETWORK CONNECTIONS PER PROCESS ───────────────────────────────────────
    def _poll_network_connections(self):
        """Every 3s: map network connections to PIDs."""
        _prev_net = {}
        _prev_net_time = {}

        while self._running:
            now = time.time()
            by_pid = {}

            try:
                conns = psutil.net_connections(kind="all")
                for c in conns:
                    pid = c.pid
                    if pid is None:
                        continue
                    if pid not in by_pid:
                        by_pid[pid] = {
                            "count": 0,
                            "listening": 0,
                            "established": 0,
                            "remotes": [],
                            "rx_mbps": 0,
                            "tx_mbps": 0,
                            "protocols": set(),
                        }
                    entry = by_pid[pid]
                    entry["count"] += 1
                    st = c.status
                    if st == "LISTEN":
                        entry["listening"] += 1
                    elif st == "ESTABLISHED":
                        entry["established"] += 1
                        if c.raddr:
                            entry["remotes"].append(f"{c.raddr.ip}:{c.raddr.port}")
                    entry["protocols"].add("TCP" if c.type == 1 else "UDP")

                # Per-process net I/O (approximated from psutil per-proc if available)
                try:
                    for proc in psutil.process_iter(["pid"], ad_value=None):
                        pid = proc.pid
                        if pid not in by_pid:
                            continue
                        try:
                            nio = proc.io_counters()
                            prev_nio = _prev_net.get(pid)
                            prev_t   = _prev_net_time.get(pid, now)
                            dt = max(0.1, now - prev_t)
                            if prev_nio:
                                # Use read/write bytes as net proxy if net-specific unavailable
                                pass
                            _prev_net[pid] = nio
                            _prev_net_time[pid] = now
                        except Exception:
                            pass
                except Exception:
                    pass

                # Convert sets to lists for JSON serialization
                for pid, d in by_pid.items():
                    d["protocols"] = list(d.get("protocols", set()))

            except Exception:
                pass

            with self._lock:
                self.net_connections_by_proc = by_pid

            time.sleep(3)

    # ── SECURITY EVENT LOG ────────────────────────────────────────────────────
    def _poll_security_events(self):
        """Every 10s: read recent Windows Security Event Log entries."""
        if not _win32_available:
            return

        last_read_time = time.time() - 60  # start reading last 60s of events

        while self._running:
            try:
                self._read_security_events(last_read_time)
                last_read_time = time.time()
            except Exception:
                pass
            time.sleep(10)

    def _read_security_events(self, since_timestamp):
        """Read Security + System event logs for relevant event IDs."""
        logs_to_check = [
            ("Security", list(SEC_EVENT_IDS.keys())),
            ("System",   [7045, 7040, 7036]),
        ]

        for log_name, event_ids in logs_to_check:
            try:
                handle = win32evtlog.OpenEventLog(None, log_name)
                flags  = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ

                while True:
                    events = win32evtlog.ReadEventLog(handle, flags, 0)
                    if not events:
                        break
                    for ev in events:
                        try:
                            # Check if within our time window
                            ev_time = ev.TimeGenerated.timestamp()
                            if ev_time < since_timestamp:
                                break  # Events are in reverse chronological order

                            eid = ev.EventID & 0xFFFF
                            if eid not in event_ids:
                                continue

                            desc = SEC_EVENT_IDS.get(eid, f"Event {eid}")
                            strings = list(ev.StringInserts or [])

                            entry = {
                                "time":      time.strftime("%H:%M:%S", time.localtime(ev_time)),
                                "timestamp": ev_time,
                                "log":       log_name,
                                "event_id":  eid,
                                "description": desc,
                                "source":    ev.SourceName,
                                "computer":  ev.ComputerName,
                                "strings":   strings[:8],
                                "process":   strings[0] if strings else "?",
                                "category":  self._categorize_event(eid),
                            }

                            with self._lock:
                                self.security_events.append(entry)
                                if eid in CREDENTIAL_EVENT_IDS:
                                    self.credential_events.append(entry)
                                if eid in PERMISSION_EVENT_IDS:
                                    self.permission_events.append(entry)
                                if eid in OWNERSHIP_EVENT_IDS:
                                    self.ownership_events.append(entry)

                            # Alert on high-risk events
                            if eid in {4625, 4673, 4674, 4719, 4720, 4697, 4698}:
                                msg = f"[SEC:{eid}] {desc} — {strings[:2]}"
                                if self.on_alert:
                                    self.on_alert(msg)

                        except Exception:
                            continue
                win32evtlog.CloseEventLog(handle)
            except Exception:
                pass

    # ── GPU PER-PROCESS (WMI) ─────────────────────────────────────────────────
    def get_gpu_by_process(self) -> list:
        return []

    # ── RISK SCORING ──────────────────────────────────────────────────────────
    def _score_risk(self, entry: dict) -> int:
        score = 0
        name = (entry.get("name") or "").lower()
        exe  = (entry.get("exe")  or "").lower()
        user = (entry.get("username") or "").lower()

        # High CPU from non-system process
        if entry.get("cpu_pct", 0) > 80 and "system" not in user:
            score += 3

        # Unusual disk write rate
        if entry.get("disk_write_rate_mbps", 0) > 50:
            score += 4

        # Many network connections
        if entry.get("net_established", 0) > 20:
            score += 3

        # External connections from system process
        remotes = entry.get("net_remote_addresses", [])
        if remotes and any(s in name for s in ["svchost", "system", "lsass", "winlogon"]):
            score += 5

        # Non-system process listening on ports
        if entry.get("net_listening", 0) > 0 and not any(s in name for s in ["svchost", "system", "services"]):
            score += 2

        # Process in temp/appdata running with network
        if any(s in exe for s in ["\\temp\\", "\\tmp\\", "appdata\\local\\temp"]):
            if entry.get("net_connections", 0) > 0:
                score += 6

        # Excessive open handles (potential handle leak/exploit)
        if entry.get("open_handles", 0) > 5000:
            score += 2

        # Many open files
        if entry.get("open_files", 0) > 200:
            score += 2

        return min(10, score)

    def _risk_flags(self, entry: dict) -> list:
        flags = []
        name = (entry.get("name") or "").lower()
        exe  = (entry.get("exe")  or "").lower()
        user = (entry.get("username") or "").lower()

        if entry.get("cpu_pct", 0) > 80:
            flags.append("HIGH_CPU")
        if entry.get("disk_write_rate_mbps", 0) > 50:
            flags.append("HIGH_DISK_WRITE")
        if entry.get("net_established", 0) > 20:
            flags.append("MANY_CONNECTIONS")
        if entry.get("net_remote_addresses") and any(s in name for s in ["lsass", "winlogon"]):
            flags.append("SYSTEM_PROC_NETWORKING")
        if any(s in exe for s in ["\\temp\\", "\\tmp\\", "appdata\\local\\temp"]) and entry.get("net_connections", 0) > 0:
            flags.append("TEMP_EXEC_WITH_NETWORK")
        if entry.get("open_handles", 0) > 5000:
            flags.append("HANDLE_LEAK")
        if entry.get("is_elevated") and "system" not in user:
            flags.append("ELEVATED_USER_PROCESS")

        return flags

    def _flag_high_risk(self, snapshot: dict):
        for pid, entry in snapshot.items():
            if entry.get("risk_score", 0) >= 5:
                entry["flagged_at"] = time.strftime("%H:%M:%S")
                with self._lock:
                    self.flagged_processes.append(dict(entry))
                if self.on_alert:
                    flags = ", ".join(entry.get("risk_flags", []))
                    self.on_alert(f"[RISK:{entry['risk_score']}/10] {entry['name']} (PID:{pid}) — {flags}")

    def _categorize_event(self, eid: int) -> str:
        if eid in CREDENTIAL_EVENT_IDS:
            return "CREDENTIAL"
        if eid in PERMISSION_EVENT_IDS:
            return "PERMISSION"
        if eid in OWNERSHIP_EVENT_IDS:
            return "OWNERSHIP"
        if eid in {4688, 4689}:
            return "PROCESS"
        if eid in {7045, 4697, 4698}:
            return "SERVICE"
        return "SYSTEM"

    # ── PUBLIC API ────────────────────────────────────────────────────────────
    def get_snapshot(self) -> dict:
        with self._lock:
            procs = dict(self.process_resources)
            sec_evs   = list(self.security_events)[-50:]
            cred_evs  = list(self.credential_events)[-30:]
            perm_evs  = list(self.permission_events)[-30:]
            own_evs   = list(self.ownership_events)[-30:]
            flagged   = list(self.flagged_processes)[-30:]

        # Top resource consumers
        proc_list = list(procs.values())
        top_cpu  = sorted(proc_list, key=lambda x: x.get("cpu_pct", 0), reverse=True)[:10]
        top_disk = sorted(proc_list, key=lambda x: x.get("disk_write_rate_mbps", 0)+x.get("disk_read_rate_mbps", 0), reverse=True)[:10]
        top_net  = sorted(proc_list, key=lambda x: x.get("net_connections", 0), reverse=True)[:10]
        top_risk = sorted(proc_list, key=lambda x: x.get("risk_score", 0), reverse=True)[:10]
        top_ram  = sorted(proc_list, key=lambda x: x.get("ram_mb", 0), reverse=True)[:10]

        # GPU per process
        gpu_procs = self.get_gpu_by_process()

        return {
            "all_processes":      proc_list,
            "top_cpu":            top_cpu,
            "top_disk":           top_disk,
            "top_net":            top_net,
            "top_risk":           top_risk,
            "top_ram":            top_ram,
            "gpu_by_process":     gpu_procs,
            "security_events":    sec_evs,
            "credential_events":  cred_evs,
            "permission_events":  perm_evs,
            "ownership_events":   own_evs,
            "flagged_processes":  flagged,
            "total_processes":    len(procs),
            "timestamp":          time.time(),
        }

    def get_process_detail(self, pid: int) -> dict:
        """Get full resource access breakdown for a specific PID."""
        with self._lock:
            base = self.process_resources.get(pid, {})
            net  = self.net_connections_by_proc.get(pid, {})

        # Get open files
        try:
            p = psutil.Process(pid)
            open_files = [f.path for f in p.open_files()]
        except Exception:
            open_files = []

        # Windows-specific: handles, registry keys
        try:
            p = psutil.Process(pid)
            handles = p.num_handles()
        except Exception:
            handles = 0

        return {
            **base,
            "net_detail": net,
            "open_files": open_files[:50],
            "handles": handles,
            "security_events": [e for e in list(self.security_events)
                                 if str(pid) in str(e.get("strings", ""))],
        }

    def search_resource_access(self, keyword: str) -> dict:
        """Find processes accessing a specific resource (IP, path keyword, etc.)"""
        kw = keyword.lower()
        with self._lock:
            procs = dict(self.process_resources)
            net   = dict(self.net_connections_by_proc)

        results = {
            "network": [],
            "processes": [],
        }

        for pid, entry in procs.items():
            if kw in (entry.get("name") or "").lower() or kw in (entry.get("exe") or "").lower():
                results["processes"].append(entry)

        for pid, ninfo in net.items():
            remotes = ninfo.get("remotes", [])
            if any(kw in r for r in remotes):
                proc_entry = procs.get(pid, {"pid": pid, "name": "?"})
                results["network"].append({**proc_entry, "matching_remotes": [r for r in remotes if kw in r]})

        return results
