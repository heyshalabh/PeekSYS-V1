"""
PeekSYS V1 - A little peek inside your machine.

Reads hardware/OS details from the computer it runs on and prints them in
tidy terminal sections. Everything is detected live: nothing is hardcoded,
nothing is stored, and nothing is sent anywhere.
"""
import datetime
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import uuid

import psutil

VERSION = "1.0"
AUTHOR = "Shalabh Suman"
TAGLINE = "A little peek inside your machine."
NA = "Not available"          # shown whenever a value cannot be detected
WIDTH = 64
LABEL_W = 20

# --------------------------------------------------------------------------
# Terminal helpers (colours, headings, aligned rows)
# --------------------------------------------------------------------------

def _enable_colors() -> bool:
    """Return True if ANSI colours should be used."""
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:  # Windows 10/11: switch the console into ANSI mode
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
        except Exception:
            return False
    return True


USE_COLOR = _enable_colors()


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


GREEN, GREY, BOLD, CYAN, YELLOW, RED = "92", "90", "1", "96", "93", "91"


def heading(title: str) -> None:
    print("\n" + paint(f" {title.upper()}", f"{BOLD};{GREEN}"))
    print(paint("-" * WIDTH, GREY))


def row(label: str, value) -> None:
    value = NA if value in (None, "", "Unknown") else value
    print(f"  {paint(label.ljust(LABEL_W), GREY)}{value}")


def bar(percent: float, size: int = 24) -> str:
    """Text usage bar, e.g. [#########...............] 38%"""
    filled = int(round(size * percent / 100))
    color = RED if percent >= 85 else YELLOW if percent >= 65 else GREEN
    return f"[{paint('#' * filled, color)}{paint('.' * (size - filled), GREY)}] {percent:.0f}%"


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} B" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024


def fmt_duration(seconds: float) -> str:
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d} days, {h} hours, {m} minutes, {s} seconds"


def run_command(cmd: list, timeout: int = 8) -> str:
    """Run a command quietly; return its output or '' on any failure."""
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                             creationflags=flags)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


LOGO = r"""
 ____           _     ______   ______   __     ___
|  _ \ ___  ___| | __/ ___\ \ / / ___|  \ \   / / |
| |_) / _ \/ _ \ |/ /\___ \\ V /\___ \   \ \ / /| |
|  __/  __/  __/   <  ___) || |  ___) |   \ V / | |
|_|   \___|\___|_|\_\|____/ |_| |____/     \_/  |_|
"""


def show_logo() -> None:
    print(paint(LOGO, f"{BOLD};{GREEN}"))
    print(f"  {paint(TAGLINE, CYAN)}   {paint('v' + VERSION, GREY)}")
    print(paint("=" * WIDTH, GREY))


# --------------------------------------------------------------------------
# Collectors - each section is a function that prints its own rows
# --------------------------------------------------------------------------

def os_name() -> str:
    system = platform.system()
    if system == "Windows":
        try:  # Windows 11 still reports release "10"; builds >= 22000 are Win 11
            build = int(platform.version().split(".")[-1])
            return "Windows 11" if build >= 22000 else f"Windows {platform.release()}"
        except ValueError:
            pass
    return f"{system} {platform.release()}".strip()


def cpu_name() -> str:
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except Exception:
            pass
    elif platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    elif platform.system() == "Darwin":
        name = run_command(["sysctl", "-n", "machdep.cpu.brand_string"])
        if name:
            return name
    return platform.processor()


def section_system() -> None:
    heading("System")
    row("Computer name", platform.node())
    row("Hostname", socket.gethostname())
    row("Operating system", os_name())
    row("OS version", platform.version())
    row("Architecture", f"{platform.machine()} ({platform.architecture()[0]})")


def section_processor() -> None:
    heading("Processor")
    row("CPU name", cpu_name())
    row("Physical cores", psutil.cpu_count(logical=False))
    row("Logical cores", psutil.cpu_count(logical=True))
    try:
        freq = psutil.cpu_freq()
        row("Frequency", f"{freq.current / 1000:.2f} GHz" if freq and freq.current else None)
        if freq and freq.max:
            row("Max frequency", f"{freq.max / 1000:.2f} GHz")
    except Exception:
        row("Frequency", None)


def section_memory() -> None:
    heading("Memory")
    vm = psutil.virtual_memory()
    row("Total RAM", fmt_bytes(vm.total))
    row("Used RAM", fmt_bytes(vm.total - vm.available))
    row("Available RAM", fmt_bytes(vm.available))
    row("Usage", bar(vm.percent))


def section_storage() -> None:
    heading("Storage")
    shown = 0
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue  # empty card reader, locked volume, ...
        shown += 1
        print(f"  {paint(part.mountpoint, BOLD)} {paint('(' + part.fstype + ')', GREY)}")
        row("  Total", fmt_bytes(usage.total))
        row("  Used", fmt_bytes(usage.used))
        row("  Free", fmt_bytes(usage.free))
        row("  Usage", bar(usage.percent))
    if not shown:
        row("Drives", None)


def detect_gpus() -> list:
    """Return a list of GPU description strings using built-in OS tools."""
    system = platform.system()
    gpus = []
    if system == "Windows":
        # PowerShell works on Windows 10/11 (wmic is removed on newer Win 11 builds)
        out = run_command(["powershell", "-NoProfile", "-Command",
                           "Get-CimInstance Win32_VideoController | ForEach-Object "
                           "{ $_.Name + '|' + $_.AdapterRAM + '|' + $_.DriverVersion }"])
        if not out:
            out = run_command(["wmic", "path", "win32_VideoController", "get",
                               "Name,AdapterRAM,DriverVersion", "/format:csv"])
            lines = [l.split(",") for l in out.splitlines() if l.count(",") >= 3][1:]
            lines = [f"{c[3]}|{c[1]}|{c[2]}" for c in lines]
        else:
            lines = out.splitlines()
        for line in lines:
            parts = (line.split("|") + ["", ""])[:3]
            name, ram, driver = (p.strip() for p in parts)
            if not name:
                continue
            info = name
            if ram.isdigit() and int(ram) > 0:  # note: Windows caps this at 4 GB
                info += f"  | VRAM {fmt_bytes(int(ram))}"
            if driver:
                info += f"  | driver {driver}"
            gpus.append(info)
    elif system == "Linux":
        for line in run_command(["lspci"]).splitlines():
            if any(k in line for k in ("VGA", "3D controller", "Display controller")):
                gpus.append(line.split(": ", 1)[-1])
    elif system == "Darwin":
        for line in run_command(["system_profiler", "SPDisplaysDataType"]).splitlines():
            if "Chipset Model" in line:
                gpus.append(line.split(":", 1)[1].strip())
    return gpus


def section_graphics() -> None:
    heading("Graphics")
    gpus = detect_gpus()
    if not gpus:
        row("GPU", None)
    for i, gpu in enumerate(gpus, 1):
        row(f"GPU {i}" if len(gpus) > 1 else "GPU", gpu)


def local_ip() -> str:
    """Local IP used for outgoing traffic. A UDP 'connect' sends no data."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None


def section_network() -> None:
    heading("Network")
    row("Local IP address", local_ip())
    mac = uuid.getnode()
    # uuid.getnode() returns a random number (multicast bit set) if no MAC is found
    row("MAC address", None if (mac >> 40) & 1 else ":".join(f"{(mac >> s) & 0xff:02X}" for s in range(40, -8, -8)))
    try:
        addrs, stats = psutil.net_if_addrs(), psutil.net_if_stats()
    except Exception:
        row("Interfaces", None)
        return
    print(paint("  Interfaces:", GREY))
    for name, entries in addrs.items():
        ipv4 = [e.address for e in entries if e.family == socket.AF_INET]
        if not ipv4:
            continue
        st = stats.get(name)
        state = "up" if st and st.isup else "down"
        speed = f", {st.speed} Mbps" if st and st.speed else ""
        row("  " + name[:LABEL_W - 3], f"{', '.join(ipv4)}  ({state}{speed})")


def section_battery() -> None:
    heading("Battery")
    try:
        batt = psutil.sensors_battery()
    except Exception:
        batt = None
    if batt is None:
        row("Battery", "No battery detected (desktop PC or virtual machine)")
        return
    row("Charge", bar(batt.percent))
    if batt.power_plugged is None:
        status = None
    else:
        status = ("Fully charged" if batt.percent >= 99.5 else "Charging") if batt.power_plugged else "Discharging"
    row("Status", status)
    if not batt.power_plugged and batt.secsleft not in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED):
        row("Time remaining", fmt_duration(batt.secsleft))


def section_python() -> None:
    heading("Python")
    row("Version", platform.python_version())
    row("Implementation", f"{platform.python_implementation()} ({platform.python_compiler()})")
    row("Executable", sys.executable)
    row("Install prefix", sys.prefix)
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    row("Virtual env", "Yes" if in_venv else "No")


def section_uptime() -> None:
    heading("System Uptime")
    try:
        boot = psutil.boot_time()
        row("Boot time", datetime.datetime.fromtimestamp(boot).strftime("%A, %d %B %Y  %H:%M:%S"))
        row("Running for", fmt_duration(time.time() - boot))
    except Exception:
        row("Boot time", None)


SECTIONS = [section_system, section_processor, section_memory, section_storage,
            section_graphics, section_network, section_battery, section_python, section_uptime]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):  # avoid crashes on unusual console encodings
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    show_logo()
    for section in SECTIONS:
        try:  # one failing section must never stop the rest
            section()
        except Exception as exc:
            row("Error", f"{section.__name__} failed ({exc.__class__.__name__})")
    print("\n" + paint("=" * WIDTH, GREY))
    print(paint(f"  Developed by {AUTHOR}", f"{BOLD};{GREEN}"))
    print(paint("  Runs 100% locally - nothing is stored or sent anywhere.", GREY) + "\n")


if __name__ == "__main__":
    main()
