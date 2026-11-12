"""Screen perception: permission-gated one-shot capture, local OCR, scenes."""

from .capture import CapturePermissionError, capture_screen, captured_screen
from .ocr import OcrError, extract_text
from .scene import active_window_info, build_scene

__all__ = [
    "CapturePermissionError",
    "OcrError",
    "capture_screen",
    "captured_screen",
    "extract_text",
    "active_window_info",
    "build_scene",
]