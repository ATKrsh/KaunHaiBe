"""
KaunHaiBe - Motherboard / System Vitals Collector
Fans, voltages, temps via WMI and psutil sensors
"""
import time

try:
    import wmi
    _wmi = wmi.WMI()
    _wmi_mss = wmi.WMI(namespace="root/WMI")
    _wmi_available = True
except Exception:
    _wmi = None
    _wmi_mss = None
    _wmi_available = False

try:
    import psutil
    _psutil_available = True
except ImportError:
    _psutil_available = False


def collect():
    result = {
        "temperatures": {},
        "fans": {},
        "voltages": {},
        "system": {},
        "timestamp": time.time()
    }

    # psutil sensors
    if _psutil_available:
        try:
            sensors = psutil.sensors_temperatures()
            if sensors:
                for name, entries in sensors.items():
                    for e in entries:
                        key = f"{name}_{e.label or 'temp'}"
                        result["temperatures"][key] = {
                            "current": e.current,
                            "high": e.high,
                            "critical": e.critical
                        }
        except Exception:
            pass

        try:
            fans = psutil.sensors_fans()
            if fans:
                for name, entries in fans.items():
                    for i, e in enumerate(entries):
                        result["fans"][f"{name}_{e.label or i}"] = e.current
        except Exception:
            pass

        try:
            batt = psutil.sensors_battery()
            if batt:
                result["battery"] = {
                    "percent": batt.percent,
                    "plugged": batt.power_plugged,
                    "secs_left": batt.secsleft if batt.secsleft != psutil.POWER_TIME_UNLIMITED else -1
                }
        except Exception:
            pass

    # WMI system info
    if _wmi_available and _wmi:
        try:
            for board in _wmi.Win32_BaseBoard():
                result["system"]["manufacturer"] = getattr(board, "Manufacturer", "N/A")
                result["system"]["product"] = getattr(board, "Product", "N/A")
                result["system"]["serial"] = getattr(board, "SerialNumber", "N/A")
                break
        except Exception:
            pass

        try:
            for cs in _wmi.Win32_ComputerSystem():
                result["system"]["model"] = getattr(cs, "Model", "N/A")
                result["system"]["total_ram_gb"] = round(int(getattr(cs, "TotalPhysicalMemory", 0) or 0) / 1e9, 2)
                result["system"]["domain"] = getattr(cs, "Domain", "N/A")
                result["system"]["num_processors"] = getattr(cs, "NumberOfProcessors", 1)
                break
        except Exception:
            pass

        try:
            for bios in _wmi.Win32_BIOS():
                result["system"]["bios_version"] = getattr(bios, "SMBIOSBIOSVersion", "N/A")
                result["system"]["bios_date"] = getattr(bios, "ReleaseDate", "N/A")
                break
        except Exception:
            pass

        # WMI thermal
        try:
            if _wmi_mss:
                for tz in _wmi_mss.MSAcpi_ThermalZoneTemperature():
                    name = getattr(tz, "InstanceName", "ThermalZone")
                    temp_k = getattr(tz, "CurrentTemperature", 0)
                    if temp_k:
                        temp_c = (temp_k / 10.0) - 273.15
                        result["temperatures"][f"ACPI_{name}"] = {
                            "current": round(temp_c, 1),
                            "high": None,
                            "critical": None
                        }
        except Exception:
            pass

    # RAM vitals
    if _psutil_available:
        try:
            import psutil
            vm = psutil.virtual_memory()
            result["ram"] = {
                "total_gb": round(vm.total / 1e9, 2),
                "available_gb": round(vm.available / 1e9, 2),
                "used_gb": round(vm.used / 1e9, 2),
                "usage_pct": vm.percent,
                "buffers_gb": round(getattr(vm, 'buffers', 0) / 1e9, 3),
                "cached_gb": round(getattr(vm, 'cached', 0) / 1e9, 3),
            }
            sw = psutil.swap_memory()
            result["swap"] = {
                "total_gb": round(sw.total / 1e9, 2),
                "used_gb": round(sw.used / 1e9, 2),
                "free_gb": round(sw.free / 1e9, 2),
                "usage_pct": sw.percent,
                "sin_mb": round(sw.sin / 1e6, 2),
                "sout_mb": round(sw.sout / 1e6, 2),
            }
        except Exception:
            pass

    return result
