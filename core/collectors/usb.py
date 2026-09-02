"""
KaunHaiBe - USB Collector
USB devices, dongles, transfer speed, health, power
"""
import time

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

try:
    import psutil
    _psutil_available = True
except ImportError:
    _psutil_available = False


_last_net_io = {}
_last_net_time = {}


def collect():
    result = {
        "devices": [],
        "hubs": [],
        "controllers": [],
        "network_adapters": [],
        "timestamp": time.time()
    }

    _wmi = _get_wmi()
    if not _wmi:
        return result

    # USB Devices
    try:
        for dev in _wmi.Win32_USBHub():
            result["hubs"].append({
                "device_id": getattr(dev, "DeviceID", ""),
                "description": getattr(dev, "Description", ""),
                "manufacturer": getattr(dev, "Manufacturer", ""),
                "name": getattr(dev, "Name", ""),
                "status": getattr(dev, "Status", ""),
                "availability": getattr(dev, "Availability", ""),
            })
    except Exception:
        pass

    try:
        for dev in _wmi.Win32_USBController():
            result["controllers"].append({
                "name": getattr(dev, "Name", ""),
                "device_id": getattr(dev, "DeviceID", ""),
                "manufacturer": getattr(dev, "Manufacturer", ""),
                "driver": getattr(dev, "DriverName", ""),
                "status": getattr(dev, "Status", ""),
            })
    except Exception:
        pass

    # Input devices (mouse, keyboard, bluetooth, wireless dongles)
    try:
        for dev in _wmi.Win32_PointingDevice():
            entry = {
                "type": "mouse/pointing",
                "name": getattr(dev, "Name", "Unknown"),
                "manufacturer": getattr(dev, "Manufacturer", ""),
                "device_id": getattr(dev, "DeviceID", ""),
                "description": getattr(dev, "Description", ""),
                "status": getattr(dev, "Status", ""),
                "device_interface": getattr(dev, "DeviceInterface", ""),
                "is_wireless": "bluetooth" in str(getattr(dev, "DeviceID", "")).lower()
                               or "hid" in str(getattr(dev, "DeviceID", "")).lower(),
                "is_bluetooth": "bluetooth" in str(getattr(dev, "Name", "")).lower()
                                or "bluetooth" in str(getattr(dev, "DeviceID", "")).lower(),
            }
            result["devices"].append(entry)
    except Exception:
        pass

    try:
        for dev in _wmi.Win32_Keyboard():
            entry = {
                "type": "keyboard",
                "name": getattr(dev, "Name", "Unknown"),
                "description": getattr(dev, "Description", ""),
                "device_id": getattr(dev, "DeviceID", ""),
                "status": getattr(dev, "Status", ""),
                "is_wireless": "bluetooth" in str(getattr(dev, "DeviceID", "")).lower()
                               or "hid" in str(getattr(dev, "DeviceID", "")).lower(),
                "is_bluetooth": "bluetooth" in str(getattr(dev, "Name", "")).lower(),
            }
            result["devices"].append(entry)
    except Exception:
        pass

    # PnP devices for USB dongles (filtered query to prevent WMI table scan hang)
    try:
        for dev in _wmi.exec_query("SELECT Name, DeviceID, Manufacturer, Status, ConfigManagerErrorCode FROM Win32_PnPEntity WHERE DeviceID LIKE '%USB%' OR DeviceID LIKE '%HID%'"):
            dev_id = str(getattr(dev, "DeviceID", ""))
            name = str(getattr(dev, "Name", ""))
            if any(k in name.lower() for k in ["bluetooth", "wireless", "dongle", "receiver", "logitech", "unifying"]):
                result["devices"].append({
                    "type": "dongle/wireless",
                    "name": name,
                    "device_id": dev_id,
                    "manufacturer": getattr(dev, "Manufacturer", ""),
                    "status": getattr(dev, "Status", ""),
                    "error_code": getattr(dev, "ConfigManagerErrorCode", 0),
                    "is_bluetooth": "bluetooth" in name.lower(),
                    "is_wireless": True
                })
    except Exception:
        pass

    # USB network adapters
    if _psutil_available:
        try:
            now = time.time()
            net_io = psutil.net_io_counters(pernic=True)
            for nic, stats in net_io.items():
                prev = _last_net_io.get(nic)
                prev_t = _last_net_time.get(nic, now)
                dt = max(0.01, now - prev_t)

                rx_rate = 0
                tx_rate = 0
                if prev:
                    rx_rate = max(0, (stats.bytes_recv - prev.bytes_recv) / dt)
                    tx_rate = max(0, (stats.bytes_sent - prev.bytes_sent) / dt)

                _last_net_io[nic] = stats
                _last_net_time[nic] = now

                result["network_adapters"].append({
                    "name": nic,
                    "bytes_sent_total": stats.bytes_sent,
                    "bytes_recv_total": stats.bytes_recv,
                    "packets_sent": stats.packets_sent,
                    "packets_recv": stats.packets_recv,
                    "errors_in": stats.errin,
                    "errors_out": stats.errout,
                    "drop_in": stats.dropin,
                    "drop_out": stats.dropout,
                    "rx_rate_mbps": round(rx_rate / 1024 / 1024, 3),
                    "tx_rate_mbps": round(tx_rate / 1024 / 1024, 3),
                })
        except Exception:
            pass

    # Input device health summary
    error_devices = [d for d in result["devices"] if d.get("error_code", 0) != 0 or d.get("status", "OK") != "OK"]
    result["error_device_count"] = len(error_devices)
    result["total_device_count"] = len(result["devices"])

    return result
