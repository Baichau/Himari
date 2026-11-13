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


def test_active_window_rect_reads_foreground_bounds(monkeypatch):
    user32 = Mock()
    user32.GetForegroundWindow.return_value = 123

    def get_rect(hwnd, pointer):
        assert hwnd == 123
        rect = pointer._obj
        rect.left, rect.top = 10, 20
        rect.right, rect.bottom = 110, 220
        return 1

    user32.GetWindowRect.side_effect = get_rect
    monkeypatch.setattr(screen.ctypes, "windll", SimpleNamespace(user32=user32))

    assert screen.active_window_rect() == {
        "left": 10, "top": 20, "width": 100, "height": 200,
    }


def test_active_window_rect_rejects_empty_or_missing_windows(monkeypatch):
    user32 = Mock()
    user32.GetForegroundWindow.return_value = 0
    monkeypatch.setattr(screen.ctypes, "windll", SimpleNamespace(user32=user32))

    try:
        screen.active_window_rect()
    except RuntimeError as exc:
        assert "active window" in str(exc)
    else:
        raise AssertionError("No foreground window must be reported as an error.")

    user32.GetForegroundWindow.return_value = 7

    def get_minimized(hwnd, pointer):
        rect = pointer._obj
        rect.left = rect.top = rect.right = rect.bottom = 0
        return 1

    user32.GetWindowRect.side_effect = get_minimized
    try:
        screen.active_window_rect()
    except RuntimeError as exc:
        assert "minimized" in str(exc)
    else:
        raise AssertionError("A zero-size window must not be captured.")


def test_analyze_can_target_another_monitor(monkeypatch):
    image = Image.new("RGB", (2, 2), "white")
    captured = []

    def fake_capture(monitor="primary"):
        captured.append(monitor)
        return image

    monkeypatch.setattr(screen, "capture", fake_capture)
    monkeypatch.setattr(screen, "ocr", lambda img: "text")

    assert screen.analyze(monitor="all") == "text"
    assert captured == ["all"]
