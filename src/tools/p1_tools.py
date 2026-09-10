import datetime
from src.tools.registry import registry, Tool

try:
    import psutil
    # Prime the CPU sampler: the first call always returns 0.0, and every call
    # after that reports usage since the previous one.
    psutil.cpu_percent(interval=None)
except ImportError:  # pragma: no cover - psutil is a hard requirement in practice
    psutil = None


# --- Telemetry helpers (shared by the tools and the HUD /stats endpoint) ---

def read_cpu_percent() -> float | None:
    if psutil is None:
        return None
    reading = psutil.cpu_percent(interval=None)
    if reading == 0.0:
        # Short-lived process: not enough time has passed since the last sample
        # for a delta to mean anything. Take one real 100ms measurement instead.
        reading = psutil.cpu_percent(interval=0.1)
    return round(reading, 1)


def read_ram_percent() -> float | None:
    if psutil is None:
        return None
    return round(psutil.virtual_memory().percent, 1)


# --- Tool Handlers ---
# Every handler takes the sanitized text, even when it ignores it, so the
# registry can invoke them uniformly.

def help_handler(text: str) -> str:
    return (
        "Tier 0 (instant): help, time, date, day, status, system status, cpu, ram\n"
        "Tier 1 (read-only files, project directory only):\n"
        "  list: <dir>        contents of a directory\n"
        "  read: <file>       contents of a text file\n"
        "  find: <pattern>    filenames matching a glob\n"
        "  search: <text>     find text inside project files\n"
        "  tree:              project layout\n"
        "Memory: 'remember: <fact>' and 'forget: <keyword>'\n"
        "Anything else goes to Deep Core."
    )


def time_handler(text: str) -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def date_handler(text: str) -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


def day_handler(text: str) -> str:
    return datetime.datetime.now().strftime("%A")


def status_handler(text: str) -> str:
    return "ULTRON P1 is online and secure."


def system_status_handler(text: str) -> str:
    cpu, ram = read_cpu_percent(), read_ram_percent()
    if cpu is None or ram is None:
        return "System nominal. All security gates active. Telemetry unavailable."
    return f"System nominal. All security gates active. CPU at {cpu} percent, memory at {ram} percent."


def cpu_handler(text: str) -> str:
    cpu = read_cpu_percent()
    if cpu is None:
        return "CPU telemetry unavailable: psutil is not installed."
    return f"CPU load is at {cpu} percent across {psutil.cpu_count(logical=True)} logical cores."


def ram_handler(text: str) -> str:
    if psutil is None:
        return "Memory telemetry unavailable: psutil is not installed."
    mem = psutil.virtual_memory()
    used_gb = (mem.total - mem.available) / (1024 ** 3)
    total_gb = mem.total / (1024 ** 3)
    return f"Memory at {mem.percent} percent. {used_gb:.1f} of {total_gb:.1f} gigabytes in use."


# --- Registration (Telling the bouncer these tools exist) ---

registry.register(Tool("help_tool", 0, help_handler))
registry.register(Tool("time_tool", 0, time_handler))
registry.register(Tool("date_tool", 0, date_handler))
registry.register(Tool("day_tool", 0, day_handler))
registry.register(Tool("status_tool", 0, status_handler))
registry.register(Tool("system_status_tool", 0, system_status_handler))
registry.register(Tool("cpu_tool", 0, cpu_handler))
registry.register(Tool("ram_tool", 0, ram_handler))
