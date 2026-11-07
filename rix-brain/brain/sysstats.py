"""系统快照：内存 / CPU / 温度。后台每 30 秒采样一次，缓存最新快照。

数据源（零第三方依赖）：
  内存: ctypes -> GlobalMemoryStatusEx
  温度: Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation
        （ACPI 热区，值=0.1°C，取 10~110°C 视为有效）
  CPU:  Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor (_Total)

供 mcp_server 的 system_snapshot 工具读取缓存，不阻塞调用方。
"""
import ctypes
import subprocess
import threading
import time

INTERVAL = 30  # 采样周期（秒）

_snapshot = {"time": 0, "data": None}
_lock = threading.Lock()


def _mem_info():
    class M(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    m = M()
    m.dwLength = ctypes.sizeof(M)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    total = m.ullTotalPhys / 1048576.0
    used = (m.ullTotalPhys - m.ullAvailPhys) / 1048576.0
    return {
        "mem_percent": int(m.dwMemoryLoad),
        "mem_used_mb": int(used),
        "mem_total_mb": int(total),
    }


def _wmi_snapshot():
    """一次 PowerShell 调用拿温度 + CPU 占用。失败返回 None。"""
    script = (
        "Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation"
        " | ForEach-Object { Write-Output ('TZ|' + $_.Name + '|' + $_.Temperature) };"
        " Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor"
        " | Where-Object { $_.Name -eq '_Total' }"
        " | ForEach-Object { Write-Output ('CPU|' + $_.PercentProcessorTime) }"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-Command", script],
            capture_output=True, timeout=15,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        text = out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return None
    temps, cpu = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("TZ|"):
            parts = line.split("|")
            if len(parts) >= 3 and parts[2].strip().isdigit():
                c = round(int(parts[2].strip()) / 10.0, 1)
                if 10 <= c <= 110:
                    temps.append({"name": parts[1].strip(), "temp_c": c})
        elif line.startswith("CPU|"):
            try:
                cpu = int(round(float(line.split("|")[1].strip())))
            except Exception:
                pass
    return {"temps": temps, "cpu_percent": cpu}


def sample():
    """采样一次，返回带时间的完整快照。"""
    data = {"mem": _mem_info(), "wmi": _wmi_snapshot()}
    return {"time": int(time.time()), "data": data}


def get_snapshot():
    """返回最新快照；缓存为空或过于陈旧时（线程未启动过）现场采样。"""
    with _lock:
        snap = _snapshot
        if snap["data"] is None or int(time.time()) - snap["time"] > INTERVAL * 2:
            snap = sample()
            _snapshot["time"] = snap["time"]
            _snapshot["data"] = snap["data"]
            return _flatten(snap)
    return _flatten(snap)


def _flatten(snap):
    data = snap.get("data") or {}
    mem = data.get("mem") or {}
    wmi = data.get("wmi") or {}
    temps = wmi.get("temps") or []
    return {
        "sampled_at": snap.get("time"),
        "age_s": int(time.time()) - snap.get("time", 0),
        "mem_percent": mem.get("mem_percent"),
        "mem_used_mb": mem.get("mem_used_mb"),
        "mem_total_mb": mem.get("mem_total_mb"),
        "cpu_percent": wmi.get("cpu_percent"),
        "temps": temps,
    }


def sampler_loop(interval=INTERVAL):
    """后台采样循环（daemon 线程）。"""
    while True:
        try:
            s = sample()
            with _lock:
                _snapshot["time"] = s["time"]
                _snapshot["data"] = s["data"]
        except Exception:
            pass
        time.sleep(interval)


def start(interval=INTERVAL):
    t = threading.Thread(target=sampler_loop, args=(interval,), daemon=True,
                         name="sysstats-sampler")
    t.start()
    return t