"""
KaunHaiBe - Services, Processes, Apps, Temp, Registry, Threads, Kernel, Interrupts Collectors
"""
import psutil
import os
import sys
import time
import winreg
import threading

try:
    import pythoncom
    import wmi
    _wmi_available = True
except Exception:
    _wmi_available = False

def _get_wmi():
    if not _wmi_available:
        return None
    try:
        pythoncom.CoInitialize()
        return wmi.WMI()
    except Exception:
        return None


# ─── SERVICES ────────────────────────────────────────────────────────────────
def collect_services():
    result = {"services": [], "timestamp": time.time()}
    try:
        for svc in psutil.win_service_iter():
            try:
                info = svc.as_dict()
                result["services"].append({
                    "name": info.get("name"),
                    "display_name": info.get("display_name"),
                    "status": info.get("status"),
                    "start_type": info.get("start_type"),
                    "pid": info.get("pid"),
                    "username": info.get("username"),
                    "description": info.get("description", ""),
                    "binpath": info.get("binpath", ""),
                })
            except Exception:
                continue
    except Exception as e:
        result["error"] = str(e)
    return result


# ─── PROCESSES ───────────────────────────────────────────────────────────────
def collect_processes():
    result = {"processes": [], "timestamp": time.time()}
    attrs = ["pid", "name", "username", "status", "cpu_percent", "memory_percent", "memory_info"]
    for proc in psutil.process_iter(attrs=attrs, ad_value=None):
        try:
            p = proc.info
            mi = p.get("memory_info")
            rss = getattr(mi, 'rss', 0) if mi else 0
            result["processes"].append({
                "pid": p.get("pid"),
                "name": p.get("name") or "?",
                "username": p.get("username") or "?",
                "status": p.get("status") or "?",
                "cpu_pct": p.get("cpu_percent") or 0,
                "ram_mb": round(rss / 1048576, 1),
                "ram_pct": p.get("memory_percent") or 0,
                "read_mb": 0,
                "write_mb": 0,
                "exe": "",
                "cmdline": "",
                "threads": 0,
                "ppid": None,
                "create_time": None,
                "status_flag": "normal",
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    result["processes"].sort(key=lambda x: x.get("cpu_pct", 0), reverse=True)
    result["top_cpu"] = result["processes"][:5]
    result["top_ram"] = sorted(result["processes"], key=lambda x: x.get("ram_pct", 0), reverse=True)[:5]
    return result


# ─── EVENT LOGS ──────────────────────────────────────────────────────────────
def collect_eventlog(max_entries=50):
    result = {"entries": [], "timestamp": time.time()}
    _wmi = _get_wmi()
    if not _wmi:
        return result
    try:
        query = ("SELECT * FROM Win32_NTLogEvent WHERE "
                 "Logfile='System' AND "
                 "(EventType=1 OR EventType=2) "  # Error=1, Warning=2
                 )
        for ev in _wmi.query(query)[:max_entries]:
            result["entries"].append({
                "type": {1: "Error", 2: "Warning"}.get(getattr(ev, "EventType", 0), "Info"),
                "source": getattr(ev, "SourceName", ""),
                "event_id": getattr(ev, "EventCode", ""),
                "time": getattr(ev, "TimeGenerated", ""),
                "category": getattr(ev, "CategoryString", ""),
                "message": str(getattr(ev, "Message", "") or "")[:200],
                "computer": getattr(ev, "ComputerName", ""),
            })
    except Exception as e:
        result["error"] = str(e)
    return result


# ─── INSTALLED APPS ──────────────────────────────────────────────────────────
def collect_apps():
    result = {"apps": [], "timestamp": time.time()}
    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    seen = set()
    for hive, path in reg_paths:
        try:
            key = winreg.OpenKey(hive, path)
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub_name = winreg.EnumKey(key, i)
                    sub = winreg.OpenKey(key, sub_name)
                    def rval(n):
                        try:
                            return winreg.QueryValueEx(sub, n)[0]
                        except Exception:
                            return None
                    name = rval("DisplayName")
                    if name and name not in seen:
                        seen.add(name)
                        result["apps"].append({
                            "name": name,
                            "version": rval("DisplayVersion"),
                            "publisher": rval("Publisher"),
                            "install_date": rval("InstallDate"),
                            "location": rval("InstallLocation"),
                            "size_mb": round(int(rval("EstimatedSize") or 0) / 1024, 1),
                            "uninstall": rval("UninstallString"),
                        })
                except Exception:
                    continue
        except Exception:
            continue
    result["count"] = len(result["apps"])
    return result


# ─── TEMP FOLDER ─────────────────────────────────────────────────────────────
def collect_temp():
    result = {"folders": [], "timestamp": time.time()}
    temp_paths = [
        os.environ.get("TEMP", ""),
        os.environ.get("TMP", ""),
        r"C:\Windows\Temp",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp"),
    ]
    seen = set()
    for path in temp_paths:
        if not path or path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        try:
            total_size = 0
            count = 0
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            s = entry.stat()
                            total_size += s.st_size
                            count += 1
                    except Exception:
                        pass
            result["folders"].append({
                "path": path,
                "file_count": count,
                "total_size_mb": round(total_size / 1e6, 2),
            })
        except Exception as e:
            result["folders"].append({"path": path, "error": str(e)})
    total_mb = sum(f.get("total_size_mb", 0) for f in result["folders"])
    result["total_size_mb"] = round(total_mb, 2)
    return result


# ─── REGISTRY ANOMALY SCAN ───────────────────────────────────────────────────
def collect_registry():
    result = {"startup_entries": [], "suspicious": [], "timestamp": time.time()}
    startup_paths = [
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
    ]
    for hive, path in startup_paths:
        try:
            key = winreg.OpenKey(hive, path)
            n_vals = winreg.QueryInfoKey(key)[1]
            for i in range(n_vals):
                try:
                    name, val, _ = winreg.EnumValue(key, i)
                    entry = {"name": name, "value": str(val)[:200], "hive": "HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM"}
                    result["startup_entries"].append(entry)
                    # Suspicious if no valid path or obfuscated
                    if any(c in str(val).lower() for c in ["powershell -enc", "cmd /c", "wscript", "cscript"]):
                        entry["flag"] = "suspicious_cmd"
                        result["suspicious"].append(entry)
                except Exception:
                    continue
        except Exception:
            continue
    result["startup_count"] = len(result["startup_entries"])
    result["suspicious_count"] = len(result["suspicious"])
    return result


# ─── THREADS ─────────────────────────────────────────────────────────────────
def collect_threads():
    result = {"total_threads": 0, "by_process": [], "timestamp": time.time()}
    try:
        total = 0
        proc_threads = []
        for proc in psutil.process_iter(["pid", "name", "num_threads"], ad_value=None):
            try:
                n = proc.info.get("num_threads") or 0
                total += n
                if n > 0:
                    proc_threads.append({
                        "pid": proc.info["pid"],
                        "name": proc.info["name"],
                        "num_threads": n
                    })
            except Exception:
                continue
        result["total_threads"] = total
        result["by_process"] = sorted(proc_threads, key=lambda x: x["num_threads"], reverse=True)[:20]
    except Exception as e:
        result["error"] = str(e)
    return result


# ─── KERNEL / SYSTEM STATS ───────────────────────────────────────────────────
def collect_kernel():
    result = {"timestamp": time.time()}
    try:
        boot_time = psutil.boot_time()
        result["boot_time"] = boot_time
        result["uptime_hours"] = round((time.time() - boot_time) / 3600, 2)
        result["uptime_days"] = round((time.time() - boot_time) / 86400, 2)

        cpu_stats = psutil.cpu_stats()
        result["ctx_switches"] = cpu_stats.ctx_switches
        result["interrupts"] = cpu_stats.interrupts
        result["soft_interrupts"] = cpu_stats.soft_interrupts
        result["syscalls"] = getattr(cpu_stats, "syscalls", 0)

        pids = psutil.pids()
        result["process_count"] = len(pids)

        result["python_threads"] = threading.active_count()
        result["platform"] = sys.platform

    except Exception as e:
        result["error"] = str(e)
    return result


# ─── INTERRUPTS ──────────────────────────────────────────────────────────────
_prev_intr_time = None
_prev_intr_count = None

def collect_interrupts():
    global _prev_intr_time, _prev_intr_count
    now = time.time()
    result = {"timestamp": now, "interrupts_per_sec": 0, "dpc_per_sec": 0, "pct_interrupt": 0.0, "pct_dpc": 0.0}
    try:
        cs = psutil.cpu_stats()
        curr_count = cs.interrupts
        if _prev_intr_count is not None and _prev_intr_time is not None:
            dt = max(0.1, now - _prev_intr_time)
            rate = int(max(0, (curr_count - _prev_intr_count) / dt))
            result["interrupts_per_sec"] = rate
        else:
            result["interrupts_per_sec"] = 0
        _prev_intr_count = curr_count
        _prev_intr_time = now
        result["syscalls"] = getattr(cs, "syscalls", 0)
    except Exception as e:
        result["error"] = str(e)
    return result
