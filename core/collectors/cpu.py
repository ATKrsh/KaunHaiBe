"""
KaunHaiBe - CPU Collector
Monitors CPU usage, frequency, power, core temps
"""
import psutil
import time

try:
    import cpuinfo
    _cpuinfo_available = True
except ImportError:
    _cpuinfo_available = False

try:
    import wmi
    _wmi = wmi.WMI()
    _wmi_available = True
except Exception:
    _wmi = None
    _wmi_available = False


_last_cpu_times = None
_cpu_info_cache = None


def get_cpu_info():
    global _cpu_info_cache
    if _cpu_info_cache:
        return _cpu_info_cache
    import platform
    info = {
        "brand": platform.processor() or "AMD Ryzen 5 7600X 6-Core Processor",
        "arch": platform.machine() or "x86_64",
        "cores_logical": psutil.cpu_count(logical=True) or 12,
        "cores_physical": psutil.cpu_count(logical=False) or 6,
        "hz_advertised": "4.70 GHz"
    }
    _cpu_info_cache = info
    return info


def collect():
    """Returns a dict with all CPU vitals."""
    result = {}
    try:
        result["usage_total"] = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        result["usage_per_core"] = per_core
        result["usage_max_core"] = max(per_core) if per_core else 0

        freq = psutil.cpu_freq()
        if freq:
            result["freq_current_mhz"] = round(freq.current, 1)
            result["freq_min_mhz"] = round(freq.min, 1)
            result["freq_max_mhz"] = round(freq.max, 1)
        else:
            result["freq_current_mhz"] = 0
            result["freq_min_mhz"] = 0
            result["freq_max_mhz"] = 0

        # CPU Temperature
        temps = {}
        try:
            sensors = psutil.sensors_temperatures()
            if sensors:
                for name, entries in sensors.items():
                    for e in entries:
                        temps[f"{name}_{e.label or 'temp'}"] = e.current
        except Exception:
            pass
        result["temperatures"] = temps

        # CPU times
        ct = psutil.cpu_times_percent(interval=None)
        result["user_pct"] = ct.user
        result["system_pct"] = ct.system
        result["idle_pct"] = ct.idle
        result["interrupt_pct"] = getattr(ct, 'interrupt', 0)
        result["dpc_pct"] = getattr(ct, 'dpc', 0)

        # Load average (Windows fallback = cpu_percent)
        load = psutil.getloadavg() if hasattr(psutil, 'getloadavg') else (result["usage_total"] / 100,) * 3
        result["load_1m"] = round(load[0], 3)
        result["load_5m"] = round(load[1], 3)
        result["load_15m"] = round(load[2], 3)

        # Power estimate (rough: usage * TDP assumption if no sensor)
        tdp_w = 65  # default estimate
        result["power_est_w"] = round((result["usage_total"] / 100.0) * tdp_w, 1)

        # Context switches, interrupts
        stats = psutil.cpu_stats()
        result["ctx_switches"] = stats.ctx_switches
        result["interrupts"] = stats.interrupts
        result["soft_interrupts"] = stats.soft_interrupts
        result["syscalls"] = getattr(stats, 'syscalls', 0)

    except Exception as e:
        result["error"] = str(e)

    result["timestamp"] = time.time()
    return result
