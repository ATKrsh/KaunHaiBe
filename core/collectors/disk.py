"""
KaunHaiBe - Disk Collector
HDD/SSD: read/write/speed/temp/health/SMART/errors
"""
import psutil
import time

try:
    from pySMART import DeviceList
    _smart_available = True
except Exception:
    _smart_available = False

try:
    import wmi
    _wmi = wmi.WMI()
    _wmi_available = True
except Exception:
    _wmi = None
    _wmi_available = False


_last_disk_io = {}
_last_disk_time = {}


def _get_smart_data():
    smart = {}
    if not _smart_available:
        return smart
    try:
        devices = DeviceList()
        for dev in devices.devices:
            if dev is None:
                continue
            name = dev.name or "Unknown"
            entry = {
                "model": dev.model,
                "serial": dev.serial,
                "firmware": dev.firmware,
                "capacity": dev.capacity,
                "interface": dev.interface,
                "health": dev.assessment,
                "temperature": dev.temperature,
                "rotation_rate": dev.rotation_rate,
                "messages": [str(m) for m in (dev.messages or [])],
                "tests": [],
            }
            # SMART attributes
            attrs = {}
            if dev.attributes:
                for a in dev.attributes:
                    if a:
                        attrs[a.name] = {
                            "value": a.value,
                            "worst": a.worst,
                            "threshold": a.thresh,
                            "raw": a.raw,
                            "failed": a.failed
                        }
            entry["smart_attrs"] = attrs
            smart[name] = entry
    except Exception as e:
        smart["error"] = str(e)
    return smart


def collect():
    global _last_disk_io, _last_disk_time

    now = time.time()
    result = {"disks": {}, "io_summary": {}, "timestamp": now}

    # Per-partition info
    try:
        partitions = psutil.disk_partitions()
        for p in partitions:
            try:
                usage = psutil.disk_usage(p.mountpoint)
                result["disks"][p.device] = {
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype,
                    "total_gb": round(usage.total / 1e9, 2),
                    "used_gb": round(usage.used / 1e9, 2),
                    "free_gb": round(usage.free / 1e9, 2),
                    "usage_pct": usage.percent,
                    "opts": p.opts,
                }
            except PermissionError:
                continue
    except Exception as e:
        result["partition_error"] = str(e)

    # IO counters with rate calculation
    try:
        io_all = psutil.disk_io_counters(perdisk=True)
        if io_all:
            for disk, io in io_all.items():
                prev = _last_disk_io.get(disk)
                prev_t = _last_disk_time.get(disk, now)
                dt = max(0.01, now - prev_t)

                read_rate = 0
                write_rate = 0
                read_iops = 0
                write_iops = 0

                if prev:
                    read_rate = max(0, (io.read_bytes - prev.read_bytes) / dt)
                    write_rate = max(0, (io.write_bytes - prev.write_bytes) / dt)
                    read_iops = max(0, (io.read_count - prev.read_count) / dt)
                    write_iops = max(0, (io.write_count - prev.write_count) / dt)

                _last_disk_io[disk] = io
                _last_disk_time[disk] = now

                entry = result["disks"].get(disk, {})
                entry.update({
                    "read_bytes_total": io.read_bytes,
                    "write_bytes_total": io.write_bytes,
                    "read_rate_bps": round(read_rate, 0),
                    "write_rate_bps": round(write_rate, 0),
                    "read_rate_mbps": round(read_rate / 1024 / 1024, 2),
                    "write_rate_mbps": round(write_rate / 1024 / 1024, 2),
                    "read_iops": round(read_iops, 1),
                    "write_iops": round(write_iops, 1),
                    "read_time_ms": getattr(io, 'read_time', 0),
                    "write_time_ms": getattr(io, 'write_time', 0),
                    "busy_time_ms": getattr(io, 'busy_time', 0),
                })
                result["disks"][disk] = entry

            # Summary totals
            total_read = sum(v.get("read_rate_mbps", 0) for v in result["disks"].values() if isinstance(v, dict))
            total_write = sum(v.get("write_rate_mbps", 0) for v in result["disks"].values() if isinstance(v, dict))
            result["io_summary"] = {
                "total_read_mbps": round(total_read, 2),
                "total_write_mbps": round(total_write, 2),
            }
    except Exception as e:
        result["io_error"] = str(e)

    # SMART data
    result["smart"] = _get_smart_data()

    # Spike indicator
    max_read = max((v.get("read_rate_mbps", 0) for v in result["disks"].values() if isinstance(v, dict)), default=0)
    max_write = max((v.get("write_rate_mbps", 0) for v in result["disks"].values() if isinstance(v, dict)), default=0)
    result["max_read_mbps"] = max_read
    result["max_write_mbps"] = max_write

    return result
