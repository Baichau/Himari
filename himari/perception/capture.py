"""Permission-gated, one-shot screen capture.

Captures never record continuously and are never written to disk. Full-screen
capture reuses the existing himari.screen pipeline; focused regions use the
same mss backend.
"""

from contextlib import contextmanager

import mss
from PIL import Image

from ..config import load as load_config
from ..screen import active_window_rect
from ..screen import capture as capture_monitor


class CapturePermissionError(PermissionError):
    """Screen capture is disabled in Settings."""


def _permissions():
    config = load_config()
    return config.get("permissions", {}) if isinstance(config, dict) else {}


def _screen_allowed():
    return bool(_permissions().get("allow_screen_capture", False))


def _active_window_allowed():
    return bool(_permissions().get("allow_active_window", False))


def configured_monitor():
    config = load_config()
    screen_config = config.get("screen", {}) if isinstance(config, dict) else {}
    value = screen_config.get("monitor", "primary")
    return "primary" if value in (None, "") else value


def _validate_region(region):
    try:
        if isinstance(region, dict):
            left, top, width, height = (
                int(region[key]) for key in ("left", "top", "width", "height")
            )
        else:
            left, top, width, height = (int(value) for value in region)
    except (KeyError, TypeError, ValueError):
        raise ValueError(
            "A capture region must be four integers: left, top, width, height."
        ) from None
    if width <= 0 or height <= 0:
        raise ValueError("Capture region width and height must be positive.")
    return {"left": left, "top": top, "width": width, "height": height}


def _grab(box):
    with mss.MSS() as screen:
        shot = screen.grab(box)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def capture_screen(region=None, monitor=None, active_window=False):
    """Capture once and return a PIL image. The caller must close it."""
    if not _screen_allowed():
        raise CapturePermissionError(
            "Permission denied: screen capture is disabled in Settings."
        )
    if active_window:
        if not _active_window_allowed():
            raise CapturePermissionError(
                "Permission denied: active-window capture is disabled in Settings."
            )
        return _grab(active_window_rect())
    if region is None:
        target = configured_monitor() if monitor is None else monitor
        target_text = str(target).strip().casefold()
        if target_text == "region":
            region = (load_config().get("screen", {}) or {}).get("region")
            if not region:
                raise ValueError(
                    "No custom screen region is saved in Settings."
                )
        elif target_text == "primary":
            return capture_monitor()
        else:
            return capture_monitor(target)
    return _grab(_validate_region(region))


@contextmanager
def captured_screen(region=None, monitor=None, active_window=False):
    """Yield a one-shot capture and always release it afterwards."""
    if monitor is None and not active_window:
        image = capture_screen(region)
    else:
        image = capture_screen(region, monitor=monitor, active_window=active_window)
    try:
        yield image
    finally:
        image.close()