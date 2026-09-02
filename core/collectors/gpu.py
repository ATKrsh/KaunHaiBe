"""
KaunHaiBe - GPU Collector
Supports NVIDIA (GPUtil), AMD/Intel (WMI fallback)
"""
import time

try:
    import GPUtil
    _gputil_available = True
except ImportError:
    _gputil_available = False

try:
    import wmi
    _wmi = wmi.WMI()
    _wmi_available = True
except Exception:
    _wmi = None
    _wmi_available = False


def _collect_nvidia():
    gpus = []
    # Try pynvml / WMI direct query without calling nvidia-smi via subprocess
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode('utf-8')
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            gpus.append({
                "id": i,
                "name": name,
                "usage_pct": float(util.gpu),
                "mem_used_mb": round(mem.used / 1024 / 1024, 1),
                "mem_total_mb": round(mem.total / 1024 / 1024, 1),
                "mem_free_mb": round(mem.free / 1024 / 1024, 1),
                "mem_usage_pct": round((mem.used / mem.total * 100), 1) if mem.total else 0,
                "temp_c": temp,
                "driver": "NVIDIA",
                "uuid": None,
                "freq_mhz": None,
                "power_w": None,
                "vendor": "NVIDIA"
            })
        pynvml.nvmlShutdown()
        if gpus:
            return gpus
    except Exception:
        pass

    # Fallback to WMI VideoController without subprocess calls
    return _collect_wmi()


def _collect_wmi():
    gpus = []
    if not _wmi_available:
        return gpus
    try:
        for vid in _wmi.Win32_VideoController():
            gpus.append({
                "id": 0,
                "name": getattr(vid, "Name", "Unknown GPU"),
                "usage_pct": None,
                "mem_used_mb": None,
                "mem_total_mb": round(int(getattr(vid, "AdapterRAM", 0) or 0) / 1024 / 1024, 0),
                "mem_free_mb": None,
                "mem_usage_pct": None,
                "temp_c": None,
                "driver": getattr(vid, "DriverVersion", "N/A"),
                "uuid": None,
                "freq_mhz": None,
                "power_w": None,
                "vendor": getattr(vid, "AdapterCompatibility", "WMI")
            })
    except Exception:
        pass
    return gpus


def collect():
    gpus = _collect_nvidia()
    if not gpus:
        gpus = _collect_wmi()

    # Try WMI perf counters for usage on all GPUs
    if _wmi_available and gpus:
        try:
            gpu_usage = 0
            for perf in _wmi.Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine():
                try:
                    val = float(getattr(perf, "UtilizationPercentage", 0) or 0)
                    gpu_usage = max(gpu_usage, val)
                except Exception:
                    pass
            if gpu_usage > 0 and gpus[0]["usage_pct"] is None:
                gpus[0]["usage_pct"] = round(gpu_usage, 1)
        except Exception:
            pass

    result = {
        "gpus": gpus,
        "count": len(gpus),
        "timestamp": time.time()
    }

    # Summary for spike detection (use first GPU)
    if gpus:
        g = gpus[0]
        result["usage_pct"] = g["usage_pct"] or 0
        result["temp_c"] = g["temp_c"]
        result["mem_usage_pct"] = g["mem_usage_pct"] or 0
    else:
        result["usage_pct"] = 0
        result["temp_c"] = None
        result["mem_usage_pct"] = 0

    return result
