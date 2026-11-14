"""Windows environment module: read-only discovery plus gated launch/close.

Discovery (installed_apps, find_app, running_processes, list_windows) is
read-only. launch_app, close_app and focus_window reuse the existing
allow_open_app setting and never force-terminate processes or guess between
duplicate matches. focus_window verifies the foreground handle afterwards.
"""

from .apps import AppInfo, find_app, installed_apps
from .enumeration import WindowInfo, focus_window, list_windows, request_window_close
from .errors import AmbiguousAppError, AppNotFoundError, WindowsEnvironmentError
from .input import ScreenInputError, click_at, press_keys, scroll_screen, type_text
from .launch import close_app, launch_app
from .processes import ProcessInfo, running_processes
from . import media_session
from .uia import (
    ScreenControlError,
    activate_control,
    click_control,
    focus_window as focus_window_uia,
    list_controls,
    set_control_text,
)

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
    "focus_window",
    "launch_app",
    "close_app",
    "request_window_close",
    "ScreenInputError",
    "ScreenControlError",
    "type_text",
    "press_keys",
    "click_at",
    "scroll_screen",
    "list_controls",
    "click_control",
    "activate_control",
    "set_control_text",
    "focus_window_uia",
    "media_session",
]