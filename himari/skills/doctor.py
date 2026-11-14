"""Read-only System Doctor: explain slowness and crashes with real evidence.

No service, registry, startup, driver or security setting is ever changed. The
doctor only reads OS counters, processes, windows, installed-app metadata and
Windows event logs, then returns bounded, redacted text.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from .common import permission, stamp

EVENT_TIMEOUT_SECONDS = 8
MAX_EVENT_CHARS = 5000
MAX_PROCESSES = 30
MAX_TOP_PROCESSES = 8

_SYSTEM_QUERY = (
    "*[System[(Level=1 or Level=2) and "
    "TimeCreated[timediff(@SystemTime) <= 86400000]]]"
)
_APP_QUERY = (
    "*[System[(Level=1 or Level=2) and "
    "TimeCreated[timediff(@SystemTime) <= 604800000]]]"
)
_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|token|secret|authorization|api[_-]?key)\b"
    r"\s*[:=]\s*\S+"
)


class DoctorError(RuntimeError):
    """Diagnostics were disabled or unavailable."""


def _psutil():
    try:
        import psutil
    except Exception as exc:
        raise DoctorError(
            "psutil is not installed, so system counters are unavailable."
        ) from exc
    return psutil


def _run(arguments, timeout=EVENT_TIMEOUT_SECONDS):
    if os.name != "nt":
        return "", "Windows event logs are only available on Windows."
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [str(item) for item in arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=flags,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "", "The Windows event log did not answer in time."
    except OSError as exc:
        return "", f"Could not run the read-only log query: {exc}"
    output = (result.stdout or "").strip()
    if not output and result.stderr:
        return "", result.stderr.strip()[:400]
    return output[:MAX_EVENT_CHARS], ""


def _redact(text):
    return _SECRET_PATTERN.sub(r"\1=<redacted>", str(text or ""))


def _event_entries(text):
    entries = []
    current = []
    for line in str(text or "").splitlines():
        value = line.rstrip()
        if not value.strip():
            if current:
                entries.append(current)
                current = []
            continue
        current.append(value)
    if current:
        entries.append(current)
    return entries


def _summarize_events(text, limit=6, match=None):
    entries = _event_entries(text)
    summaries = []
    wanted = str(match or "").casefold()
    for entry in entries:
        body = _redact("\n".join(entry))
        if wanted and wanted not in body.casefold():
            continue
        values = {}
        description = []
        for line in entry:
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                if key in {"Date", "Level", "Source", "Event ID", "Task Category", "Computer"}:
                    values[key] = value.strip()
                    continue
            description.append(line.strip())
        description_text = " ".join(description)[:500]
        summaries.append(
            {
                "date": values.get("Date", ""),
                "level": values.get("Level", ""),
                "source": values.get("Source", ""),
                "event_id": values.get("Event ID", ""),
                "detail": description_text,
            }
        )
        if len(summaries) >= limit:
            break
    return summaries


def recent_system_events(limit=6):
    output, error = _run(
        ["wevtutil", "qe", "System", f"/q:{_SYSTEM_QUERY}", f"/c:{max(1, int(limit) * 3)}", "/rd:true", "/f:text"]
    )
    if error:
        return [], error
    return _summarize_events(output, limit), ""


def recent_app_events(match=None, limit=8):
    output, error = _run(
        ["wevtutil", "qe", "Application", f"/q:{_APP_QUERY}", "/c:40", "/rd:true", "/f:text"]
    )
    if error:
        return [], error
    return _summarize_events(output, limit, match=match), ""


def _bytes_gb(value):
    try:
        return f"{float(value) / (1024 ** 3):.1f} GB"
    except (TypeError, ValueError):
        return "unknown"


def _uptime_text(seconds):
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _gpu_lines():
    nvidia = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "NVIDIA Corporation/NVSMI/nvidia-smi.exe"
    executable = str(nvidia) if nvidia.is_file() else "nvidia-smi"
    output, error = _run(
        [
            executable,
            "--query-gpu=name,memory.total,memory.used,temperature.gpu,utilization.gpu",
            "--format=csv,noheader",
        ],
        timeout=5,
    )
    if error or not output:
        return []
    return ["GPU: " + " | ".join(line.strip() for line in output.splitlines()[:3])]


def _top_processes(psutil):
    rows = []
    for process in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            info = process.info
            rows.append(
                (
                    float(info.get("memory_percent") or 0),
                    str(info.get("name") or "unknown"),
                    int(info.get("pid") or 0),
                )
            )
        except Exception:
            continue
    rows.sort(reverse=True)
    return [
        f"{name} (pid {pid}): {percent:.1f}% memory"
        for percent, name, pid in rows[:MAX_TOP_PROCESSES]
    ]


def _disk_lines(psutil):
    lines = []
    for partition in psutil.disk_partitions(all=False)[:6]:
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except Exception:
            continue
        lines.append(
            f"{partition.device} ({partition.fstype or 'unknown'}): "
            f"{_bytes_gb(usage.used)} used / {_bytes_gb(usage.total)} "
            f"({usage.percent:.0f}%), {_bytes_gb(usage.free)} free"
        )
    return lines


def _battery_lines(psutil):
    try:
        battery = psutil.sensors_battery()
    except Exception:
        battery = None
    if battery is None:
        return []
    plug = "charging" if battery.power_plugged else "on battery"
    return [f"Battery: {battery.percent:.0f}% ({plug})."]


def inspect_system():
    if not permission("allow_system_diagnostics"):
        return (
            "Permission denied: enable 'Allow read-only system diagnostics' "
            "in Settings → Permissions."
        )
    psutil = _psutil()
    lines = ["System Doctor — read-only snapshot", ""]
    try:
        lines.append(f"Captured: {stamp()}")
        lines.append(f"Platform: {os.name} {os.environ.get('OS', '')}".strip())
        try:
            import platform

            lines.append(f"Windows: {platform.platform()}")
        except Exception:
            pass
        boot = psutil.boot_time()
        lines.append(f"Uptime: {_uptime_text(time.time() - boot)}")
        lines.append(
            f"CPU: {psutil.cpu_count(logical=True)} logical core(s), "
            f"{psutil.cpu_percent(interval=0.2):.0f}% busy right now"
        )
        memory = psutil.virtual_memory()
        lines.append(
            f"Memory: {_bytes_gb(memory.used)} used / {_bytes_gb(memory.total)} "
            f"({memory.percent:.0f}%), {_bytes_gb(memory.available)} available"
        )
        swap = psutil.swap_memory()
        if swap.total:
            lines.append(
                f"Swap: {_bytes_gb(swap.used)} / {_bytes_gb(swap.total)} "
                f"({swap.percent:.0f}%)"
            )
        lines.extend(_disk_lines(psutil))
        lines.extend(_gpu_lines())
        lines.extend(_battery_lines(psutil))
        lines.append("")
        lines.append("Top memory users:")
        lines.extend("  " + item for item in _top_processes(psutil))
    except Exception as exc:
        lines.append(f"A system counter could not be read: {exc}")

    events, error = recent_system_events(6)
    lines.append("")
    lines.append("Recent System-log warnings and errors (last 24h):")
    if error:
        lines.append("  " + error)
    elif not events:
        lines.append("  No level 1–2 entries were found.")
    else:
        for event in events:
            lines.append(
                f"  {event['date']} [{event['level']}] {event['source']} "
                f"event {event['event_id']}: {event['detail'][:220]}"
            )
    lines.append("")
    lines.append(
        "This report is read-only. Himari will not change services, registry, "
        "startup items, drivers or security settings."
    )
    return "\n".join(lines)


def _matching_processes(psutil, name):
    wanted = str(name or "").casefold()
    matches = []
    for process in psutil.process_iter(
        ["pid", "name", "status", "memory_info", "cpu_percent", "create_time", "num_threads"]
    ):
        try:
            info = process.info
            process_name = str(info.get("name") or "")
            stem = process_name.casefold().removesuffix(".exe")
            if not wanted or not (wanted in process_name.casefold() or wanted in stem):
                continue
            memory = info.get("memory_info")
            matches.append(
                {
                    "pid": int(info.get("pid") or 0),
                    "name": process_name,
                    "status": str(info.get("status") or ""),
                    "memory_mb": round((memory.rss if memory else 0) / (1024 ** 2), 1),
                    "cpu": float(info.get("cpu_percent") or 0),
                    "threads": int(info.get("num_threads") or 0),
                    "created": stamp(info.get("create_time") or 0),
                }
            )
        except Exception:
            continue
    matches.sort(key=lambda item: item["pid"])
    return matches[:MAX_PROCESSES]


def diagnose_program(name):
    if not permission("allow_system_diagnostics"):
        return (
            "Permission denied: enable 'Allow read-only system diagnostics' "
            "in Settings → Permissions."
        )
    requested = str(name or "").strip()
    if not requested:
        return "Tell me which program or game to diagnose."
    psutil = _psutil()
    lines = [f"System Doctor — diagnosing '{requested}' (read-only)", ""]

    try:
        from ..windows import find_app, list_windows

        matches = find_app(requested)[:5]
    except Exception as exc:
        matches = []
        lines.append(f"Installed-app lookup failed: {exc}")
    if matches:
        lines.append("Installed matches:")
        for app in matches:
            lines.append(
                f"  - {app.name} [{app.source}] -> {Path(app.target).name or app.target}"
            )
    else:
        lines.append("No installed-app match was found. I will still check processes.")

    processes = _matching_processes(psutil, requested)
    lines.append("")
    if processes:
        lines.append("Running processes:")
        for item in processes:
            lines.append(
                f"  - {item['name']} (pid {item['pid']}): {item['status']}, "
                f"{item['memory_mb']} MB, {item['threads']} threads, "
                f"started {item['created']}"
            )
    else:
        lines.append("Not running: no matching process is currently open.")

    try:
        windows = [
            window
            for window in list_windows()
            if requested.casefold() in window.title.casefold()
            or requested.casefold() in window.process_name.casefold()
        ]
    except Exception:
        windows = []
    if windows:
        lines.append("")
        lines.append("Visible windows:")
        for window in windows[:8]:
            lines.append(f"  - {window.title} [{window.process_name}]")

    events, error = recent_app_events(requested, 6)
    lines.append("")
    lines.append("Recent Application-log warnings/errors mentioning it (last 7 days):")
    if error:
        lines.append("  " + error)
    elif not events:
        lines.append("  No matching crash or error entry was found in the recent log.")
    else:
        for event in events:
            lines.append(
                f"  {event['date']} [{event['level']}] {event['source']} "
                f"event {event['event_id']}: {event['detail'][:260]}"
            )

    lines.append("")
    lines.append("Safe next steps:")
    lines.append("  1. Close and reopen the program normally (Himari never force-kills it).")
    lines.append("  2. Check the program's own update screen for a newer version.")
    lines.append("  3. Note the exact error text and ask Himari to read it with you.")
    lines.append("  4. If crashes continue, use Windows Settings to check for updates.")
    lines.append(
        "Himari did not and will not modify services, registry values, startup "
        "items, drivers or security protections."
    )
    return "\n".join(lines)


TOOLS = [
    {
        "name": "inspect_system",
        "confirm": False,
        "timeout_seconds": 40,
        "spec": {
            "type": "function",
            "function": {
                "name": "inspect_system",
                "description": (
                    "Read-only System Doctor snapshot: uptime, CPU, memory, disks, "
                    "GPU when available, top memory users and recent Windows System "
                    "log errors. It never changes anything."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "fn": inspect_system,
    },
    {
        "name": "diagnose_program",
        "confirm": False,
        "timeout_seconds": 40,
        "spec": {
            "type": "function",
            "function": {
                "name": "diagnose_program",
                "description": (
                    "Read-only diagnosis of one app or game: installed matches, "
                    "running processes, visible windows and recent crash/error "
                    "events. Use it when something is slow, frozen or crashing. "
                    "Never force-terminates or changes system settings."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "App, game or process name.",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
        "fn": diagnose_program,
    },
]
