"""Windows environment module: read-only discovery plus gated launch/close.

Discovery (installed_apps, find_app, running_processes, list_windows) is
read-only. launch_app and close_app reuse the existing allow_open_app setting
and never force-terminate processes or guess between duplicate matches.
"""

from .apps import AppInfo, find_app, installed_apps
from .enumeration import WindowInfo, list_windows, request_window_close
from .errors import AmbiguousAppError, AppNotFoundError, WindowsEnvironmentError
from .launch import close_app, launch_app
from .processes import ProcessInfo, running_processes

__all__ = [
    "AppInfo",
    "ProcessInfo",
    "WindowInfo",
    "AmbiguousAppError",
    "AppNotFoundError",
    "WindowsEnvironmentError",
    "installed_apps",
    "running_processes",
    "find_app",
    "list_windows",
    "launch_app",
    "close_app",
    "request_window_close",
]