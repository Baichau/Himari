"""Permission-gated, one-shot screen capture.

Captures never record continuously and are never written to disk. Full-screen
capture reuses the existing himari.screen pipeline; focused regions use the
same mss backend.
"""

from contextlib import contextmanager

import mss
from PIL import Image

from ..config import load as load_config
from ..screen import capture as capture_monitor


class CapturePermissionError(PermissionError):
    """Screen capture is disabled in Settings."""


def _screen_allowed():
    config = load_config()
    permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
    return bool(permissions.get("allow_screen_capture", False))


def _validate_region(region):
    try:
        left, top, width, height = (int(value) for value in region)
    except (TypeError, ValueError):
        raise ValueError(
            "A capture region must be four integers: left, top, width, height."
        ) from None
    if width <= 0 or height <= 0:
        raise ValueError("Capture region width and height must be positive.")
    return {"left": left, "top": top, "width": width, "height": height}


def capture_screen(region=None):
    """Capture once and return a PIL image. The caller must close it."""
    if not _screen_allowed():
        raise CapturePermissionError(
            "Permission denied: screen capture is disabled in Settings."
        )
    if region is None:
        return capture_monitor()
    box = _validate_region(region)
    with mss.MSS() as screen:
        shot = screen.grab(box)
        return Image.frombytes("RGB", shot.size, shot.rgb)


@contextmanager
def captured_screen(region=None):
    """Yield a one-shot capture and always release it afterwards."""
    image = capture_screen(region)
    try:
        yield image
    finally:
        image.close()