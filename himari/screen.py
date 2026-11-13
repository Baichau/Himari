import asyncio
import ctypes
import logging
import os
from ctypes import wintypes

import mss
from PIL import Image

log=logging.getLogger("himari.screen")


def capture(monitor="primary"):
    with mss.MSS() as screen:
        if monitor == "all":
            box = screen.monitors[0]
        elif monitor == "primary":
            box = screen.monitors[1]
        else:
            try:
                index = int(monitor)
                box = screen.monitors[index]
            except (ValueError, IndexError):
                raise ValueError(f"Unknown screen monitor: {monitor}") from None
        shot = screen.grab(box)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def active_window_rect():
    """Return the foreground window's screen rectangle, or raise RuntimeError."""
    if os.name != "nt":
        raise RuntimeError("Active-window capture is only available on Windows.")
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        raise RuntimeError("Windows did not report an active window.")
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Windows could not read the active window's bounds.")
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        raise RuntimeError(
            "The active window is minimized or has no visible area, so it cannot be captured."
        )
    return {"left": int(rect.left), "top": int(rect.top), "width": width, "height": height}


def capture_active_window():
    box = active_window_rect()
    with mss.MSS() as screen:
        shot = screen.grab(box)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def ocr(img):
    async def recognize(image_bytes):
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(image_bytes)
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError(
                "Windows OCR is unavailable. Install an OCR language in Windows Settings."
            )
        result = await engine.recognize_async(bitmap)
        return result.text.strip()

    try:
        from io import BytesIO

        image_buffer = BytesIO()
        img.save(image_buffer, format="PNG")
        return asyncio.run(recognize(image_buffer.getvalue()))
    except Exception as e:
        raise RuntimeError(f"Windows screen text recognition failed: {e}") from e
    finally:
        img.close()


def analyze(monitor="primary", active_window=False):
    if active_window:
        image = capture_active_window()
    elif monitor == "primary":
        image = capture()
    else:
        image = capture(monitor)
    try:
        text = ocr(image)
    finally:
        image.close()
    if not text:
        if active_window:
            return "No readable text was detected in the active window."
        return "No readable text was detected on the captured screen."
    return text[:8000]
