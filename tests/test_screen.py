from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image

from himari import screen


def test_ocr_extracts_text_from_an_in_memory_image(monkeypatch):
    import winrt.windows.graphics.imaging as imaging
    import winrt.windows.media.ocr as windows_ocr
    import winrt.windows.storage.streams as streams

    image = Image.new("RGB", (4, 4), "white")
    captured_bytes = []

    class MemoryStream:
        def seek(self, offset):
            assert offset == 0

    stream = MemoryStream()

    class Writer:
        def __init__(self, value):
            assert value is stream

        def write_bytes(self, data):
            captured_bytes.append(bytes(data))

        async def store_async(self):
            return len(captured_bytes[0])

        async def flush_async(self):
            return True

        def detach_stream(self):
            return None

    class Decoder:
        async def get_software_bitmap_async(self):
            return "bitmap"

    class BitmapDecoder:
        @staticmethod
        async def create_async(value):
            assert value is stream
            return Decoder()

    class Engine:
        async def recognize_async(self, bitmap):
            assert bitmap == "bitmap"
            return SimpleNamespace(text="recognized text")

    monkeypatch.setattr(streams, "InMemoryRandomAccessStream", lambda: stream)
    monkeypatch.setattr(streams, "DataWriter", Writer)
    monkeypatch.setattr(imaging, "BitmapDecoder", BitmapDecoder)
    monkeypatch.setattr(
        windows_ocr.OcrEngine,
        "try_create_from_user_profile_languages",
        staticmethod(lambda: Engine()),
    )

    assert screen.ocr(image) == "recognized text"
    assert captured_bytes and captured_bytes[0].startswith(b"\x89PNG")
    try:
        image.getpixel((0, 0))
    except ValueError:
        pass
    else:
        raise AssertionError("OCR should release the screenshot image after recognition.")


def test_capture_uses_primary_monitor_without_a_settings_gate(monkeypatch):
    screenshot = SimpleNamespace(size=(1, 1), rgb=b"\x10\x20\x30")
    monitor = {"left": 0, "top": 0, "width": 1, "height": 1, "is_primary": True}

    class FakeScreen:
        monitors = [{}, monitor]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def grab(self, region):
            assert region is monitor
            return screenshot

    monkeypatch.setattr(screen.mss, "MSS", FakeScreen)

    image = screen.capture()

    assert image.getpixel((0, 0)) == (16, 32, 48)
    image.close()


def test_analyze_discards_the_capture_after_extracting_text(monkeypatch):
    image = Image.new("RGB", (4, 4), "white")
    recognized_image = Mock(return_value="visible text")
    monkeypatch.setattr(screen, "capture", lambda: image)
    monkeypatch.setattr(screen, "ocr", recognized_image)

    result = screen.analyze()

    assert result == "visible text"
    recognized_image.assert_called_once_with(image)
    try:
        image.getpixel((0, 0))
    except ValueError:
        pass
    else:
        raise AssertionError("The screenshot image should be closed after OCR.")
