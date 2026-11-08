import asyncio
import logging
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


def analyze():
    image = capture()
    try:
        text = ocr(image)
    finally:
        image.close()
    if not text:
        return "No readable text was detected on the captured screen."
    return text[:8000]
