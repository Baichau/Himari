"""Structured one-shot screen scenes: local text plus window metadata.

Scenes contain only structured text. Images are discarded immediately, nothing
is saved to disk, and no image is sent to Ollama from this module.
"""

import ctypes
import os
from datetime import datetime, timezone

from ..config import load as load_config
from ..windows import list_windows
from ..windows.enumeration import _get_user32, _process_name
from .capture import CapturePermissionError, _screen_allowed, captured_screen
from .ocr import OcrError, extract_text

MAX_UI_ELEMENTS = 30
MAX_TEXT_LINES = 200
MAX_LINE_LENGTH = 500


def _active_window_allowed():
    config = load_config()
    permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
    return bool(permissions.get("allow_active_window", False))


def active_window_info():
    """Return (title, process_name) of the foreground window, if permitted."""
    if not _active_window_allowed() or os.name != "nt":
        return "", ""
    try:
        user32 = _get_user32()
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", ""
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(max(int(length), 0) + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return buffer.value.strip(), _process_name(int(pid.value))
    except OSError:
        return "", ""


def _ui_elements():
    """Window-level UI metadata; control-level automation is out of scope."""
    elements = []
    for window in list_windows()[:MAX_UI_ELEMENTS]:
        elements.append({
            "type": "window",
            "title": window.title[:MAX_LINE_LENGTH],
            "process": window.process_name,
            "handle": window.hwnd,
        })
    return elements


def build_scene(region=None, monitor=None, active_window=False):
    """Capture once, OCR locally, and return a structured scene.

    Raises CapturePermissionError when screen capture is disabled. OCR
    failures are reported in ``ocr_error`` with an empty visible_text list.
    """
    if not _screen_allowed():
        raise CapturePermissionError(
            "Permission denied: screen capture is disabled in Settings."
        )
    title, application = active_window_info()
    scene = {
        "application": application,
        "window_title": title,
        "visible_text": [],
        "ui_elements": _ui_elements(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        if monitor is None and not active_window:
            with captured_screen(region) as image:
                lines = extract_text(image)
        else:
            with captured_screen(
                region, monitor=monitor, active_window=active_window
            ) as image:
                lines = extract_text(image)
    except OcrError as exc:
        scene["ocr_error"] = str(exc)
        return scene
    scene["visible_text"] = [line[:MAX_LINE_LENGTH] for line in lines[:MAX_TEXT_LINES]]
    return scene