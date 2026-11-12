"""Read-only listing of running processes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    exe: str | None


def running_processes():
    import psutil

    processes = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        if not info:
            continue
        processes.append(ProcessInfo(
            pid=int(info.get("pid") or 0),
            name=str(info.get("name") or ""),
            exe=info.get("exe"),
        ))
    return processes