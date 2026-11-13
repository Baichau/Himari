import os
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from himari.perception import (
    CapturePermissionError,
    OcrError,
    active_window_info,
    build_scene,
    capture_screen,
    captured_screen,
    extract_text,
)
from himari.perception import capture, ocr, scene
from himari.windows import WindowInfo

SCREEN_ON = {"permissions": {"allow_screen_capture": True}}
SCREEN_OFF = {"permissions": {"allow_screen_capture": False}}


def test_capture_requires_permission(monkeypatch):
    monkeypatch.setattr(capture, "load_config", lambda: SCREEN_OFF)
    monkeypatch.setattr(capture, "capture_monitor", Mock(side_effect=AssertionError("must not capture")))

    with pytest.raises(CapturePermissionError):
        capture_screen()


def test_fullscreen_capture_reuses_existing_pipeline(monkeypatch):
    image = Mock()
    monkeypatch.setattr(capture, "load_config", lambda: SCREEN_ON)
    monkeypatch.setattr(capture, "capture_monitor", Mock(return_value=image))

    assert capture_screen() is image


def test_region_capture_grabs_the_requested_box(monkeypatch):
    grabbed = []

    class FakeMSS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def grab(self, box):
            grabbed.append(box)
            return SimpleNamespace(size=(2, 2), rgb=b"\x00" * 12)

    monkeypatch.setattr(capture, "load_config", lambda: SCREEN_ON)
    monkeypatch.setattr(capture, "mss", SimpleNamespace(MSS=FakeMSS))

    image = capture_screen(region=(10, 20, 2, 2))

    assert grabbed == [{"left": 10, "top": 20, "width": 2, "height": 2}]
    assert image.size == (2, 2)
    image.close()


def test_region_validation_rejects_bad_boxes(monkeypatch):
    monkeypatch.setattr(capture, "load_config", lambda: SCREEN_ON)
    monkeypatch.setattr(capture, "mss", Mock(side_effect=AssertionError("must not capture")))

    with pytest.raises(ValueError):
        capture_screen(region=(0, 0, -5, 10))
    with pytest.raises(ValueError):
        capture_screen(region=(0, 0, 10))
    with pytest.raises(ValueError):
        capture_screen(region=("a", "b", "c", "d"))


def test_captured_screen_always_releases_the_image(monkeypatch):
    image = Mock()
    monkeypatch.setattr(capture, "capture_screen", lambda region=None: image)

    with captured_screen() as captured:
        assert captured is image
    image.close.assert_called_once()

    image.reset_mock()
    with pytest.raises(RuntimeError):
        with captured_screen():
            raise RuntimeError("boom")
    image.close.assert_called_once()


def test_extract_text_returns_clean_lines(monkeypatch):
    monkeypatch.setattr(ocr, "_windows_ocr", lambda image: "Line one\n\n  Line two  \n")

    assert extract_text(Mock()) == ["Line one", "Line two"]


def test_extract_text_reports_failure_without_inventing_content(monkeypatch):
    monkeypatch.setattr(ocr, "_windows_ocr", Mock(side_effect=RuntimeError("no OCR language")))

    with pytest.raises(OcrError, match="no OCR language"):
        extract_text(Mock())


def test_build_scene_requires_capture_permission(monkeypatch):
    monkeypatch.setattr(scene, "_screen_allowed", lambda: False)
    monkeypatch.setattr(scene, "extract_text", Mock(side_effect=AssertionError("must not OCR")))

    with pytest.raises(CapturePermissionError):
        build_scene()


def test_build_scene_returns_the_structured_scene(monkeypatch):
    image = Mock()

    @contextmanager
    def fake_capture(region=None):
        try:
            yield image
        finally:
            image.close()

    monkeypatch.setattr(scene, "_screen_allowed", lambda: True)
    monkeypatch.setattr(scene, "active_window_info", lambda: ("Document - Editor", "editor.exe"))
    monkeypatch.setattr(scene, "_ui_elements", lambda: [{"type": "window", "title": "Document"}])
    monkeypatch.setattr(scene, "captured_screen", fake_capture)
    monkeypatch.setattr(scene, "extract_text", lambda img: ["hello", "world"])

    result = build_scene()

    assert set(result) == {"application", "window_title", "visible_text", "ui_elements", "timestamp"}
    assert result["application"] == "editor.exe"
    assert result["window_title"] == "Document - Editor"
    assert result["visible_text"] == ["hello", "world"]
    assert result["ui_elements"] == [{"type": "window", "title": "Document"}]
    assert datetime.fromisoformat(result["timestamp"]).tzinfo is not None
    image.close.assert_called_once()


def test_build_scene_reports_ocr_errors_without_inventing_text(monkeypatch):
    image = Mock()

    @contextmanager
    def fake_capture(region=None):
        try:
            yield image
        finally:
            image.close()

    monkeypatch.setattr(scene, "_screen_allowed", lambda: True)
    monkeypatch.setattr(scene, "active_window_info", lambda: ("", ""))
    monkeypatch.setattr(scene, "_ui_elements", lambda: [])
    monkeypatch.setattr(scene, "captured_screen", fake_capture)
    monkeypatch.setattr(scene, "extract_text", Mock(side_effect=OcrError("OCR unavailable")))

    result = build_scene()

    assert result["visible_text"] == []
    assert "OCR unavailable" in result["ocr_error"]
    image.close.assert_called_once()


def test_build_scene_pipeline_closes_the_image(monkeypatch):
    image = Mock()
    monkeypatch.setattr(capture, "load_config", lambda: SCREEN_ON)
    monkeypatch.setattr(capture, "capture_monitor", lambda: image)
    monkeypatch.setattr(ocr, "_windows_ocr", lambda img: "screen text")
    monkeypatch.setattr(scene, "active_window_info", lambda: ("", ""))
    monkeypatch.setattr(scene, "_ui_elements", lambda: [])

    result = build_scene()

    assert result["visible_text"] == ["screen text"]
    image.close.assert_called()


def test_active_window_info_is_empty_without_permission(monkeypatch):
    monkeypatch.setattr(scene, "load_config", lambda: {"permissions": {"allow_active_window": False}})

    assert active_window_info() == ("", "")


@pytest.mark.skipif(os.name != "nt", reason="Windows-native foreground window")
def test_active_window_info_reads_title_and_process(monkeypatch):
    import ctypes

    def get_text(hwnd, buffer, size):
        buffer.value = "Focused App"
        return len(buffer.value)

    def get_pid(hwnd, ref):
        ref._obj.value = 42
        return 1

    fake_user32 = SimpleNamespace(
        GetForegroundWindow=lambda: 5,
        GetWindowTextLengthW=lambda hwnd: 11,
        GetWindowTextW=get_text,
        GetWindowThreadProcessId=get_pid,
    )
    monkeypatch.setattr(scene, "_active_window_allowed", lambda: True)
    monkeypatch.setattr(scene, "_get_user32", lambda: fake_user32)
    monkeypatch.setattr(scene, "_process_name", lambda pid: "app.exe" if pid == 42 else "")

    assert active_window_info() == ("Focused App", "app.exe")


def test_ui_elements_are_structured_and_bounded(monkeypatch):
    windows = [WindowInfo(i, f"Window {i}", i, "app.exe") for i in range(scene.MAX_UI_ELEMENTS + 10)]
    monkeypatch.setattr(scene, "list_windows", lambda: windows)

    elements = scene._ui_elements()

    assert len(elements) == scene.MAX_UI_ELEMENTS
    assert elements[0] == {"type": "window", "title": "Window 0", "process": "app.exe", "handle": 0}


def test_scene_text_is_bounded(monkeypatch):
    image = Mock()

    @contextmanager
    def fake_capture(region=None):
        yield image

    long_lines = ["x" * 900] * (scene.MAX_TEXT_LINES + 50)
    monkeypatch.setattr(scene, "_screen_allowed", lambda: True)
    monkeypatch.setattr(scene, "active_window_info", lambda: ("", ""))
    monkeypatch.setattr(scene, "_ui_elements", lambda: [])
    monkeypatch.setattr(scene, "captured_screen", fake_capture)
    monkeypatch.setattr(scene, "extract_text", lambda img: long_lines)

    result = build_scene()

    assert len(result["visible_text"]) == scene.MAX_TEXT_LINES
    assert all(len(line) == scene.MAX_LINE_LENGTH for line in result["visible_text"])

def test_capture_uses_the_configured_monitor(monkeypatch):
    image = Mock()
    capture_mock = Mock(return_value=image)
    monkeypatch.setattr(
        capture,
        "load_config",
        lambda: {
            "permissions": {"allow_screen_capture": True},
            "screen": {"monitor": "2"},
        },
    )
    monkeypatch.setattr(capture, "capture_monitor", capture_mock)

    assert capture_screen() is image
    capture_mock.assert_called_once_with("2")


def test_explicit_monitor_overrides_the_configured_one(monkeypatch):
    image = Mock()
    capture_mock = Mock(return_value=image)
    monkeypatch.setattr(
        capture,
        "load_config",
        lambda: {
            "permissions": {"allow_screen_capture": True},
            "screen": {"monitor": "2"},
        },
    )
    monkeypatch.setattr(capture, "capture_monitor", capture_mock)

    assert capture_screen(monitor="all") is image
    capture_mock.assert_called_once_with("all")


def test_active_window_capture_requires_its_permission(monkeypatch):
    monkeypatch.setattr(capture, "load_config", lambda: SCREEN_ON)

    with pytest.raises(CapturePermissionError, match="active-window"):
        capture_screen(active_window=True)


def test_active_window_capture_grabs_the_foreground_rect(monkeypatch):
    grabbed = []
    rect = {"left": 5, "top": 6, "width": 300, "height": 200}

    class FakeMSS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def grab(self, box):
            grabbed.append(box)
            return SimpleNamespace(size=(2, 2), rgb=b"\x00" * 12)

    monkeypatch.setattr(
        capture,
        "load_config",
        lambda: {"permissions": {
            "allow_screen_capture": True,
            "allow_active_window": True,
        }},
    )
    monkeypatch.setattr(capture, "active_window_rect", lambda: rect)
    monkeypatch.setattr(capture, "mss", SimpleNamespace(MSS=FakeMSS))

    image = capture_screen(active_window=True)

    assert grabbed == [rect]
    image.close()


def test_configured_region_capture_grabs_the_saved_box(monkeypatch):
    grabbed = []
    region = {"left": 40, "top": 50, "width": 2, "height": 2}

    class FakeMSS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def grab(self, box):
            grabbed.append(box)
            return SimpleNamespace(size=(2, 2), rgb=b"\x00" * 12)

    monkeypatch.setattr(
        capture,
        "load_config",
        lambda: {
            "permissions": {"allow_screen_capture": True},
            "screen": {"monitor": "region", "region": region},
        },
    )
    monkeypatch.setattr(capture, "mss", SimpleNamespace(MSS=FakeMSS))

    image = capture_screen()

    assert grabbed == [region]
    image.close()


def test_configured_region_without_a_saved_box_is_refused(monkeypatch):
    monkeypatch.setattr(
        capture,
        "load_config",
        lambda: {
            "permissions": {"allow_screen_capture": True},
            "screen": {"monitor": "region"},
        },
    )
    monkeypatch.setattr(capture, "mss", Mock(side_effect=AssertionError("must not capture")))

    with pytest.raises(ValueError, match="No custom screen region"):
        capture_screen()


def test_region_accepts_a_mapping_from_the_ui(monkeypatch):
    grabbed = []

    class FakeMSS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def grab(self, box):
            grabbed.append(box)
            return SimpleNamespace(size=(2, 2), rgb=b"\x00" * 12)

    monkeypatch.setattr(capture, "load_config", lambda: SCREEN_ON)
    monkeypatch.setattr(capture, "mss", SimpleNamespace(MSS=FakeMSS))

    image = capture_screen(region={"left": 1, "top": 2, "width": 2, "height": 2})

    assert grabbed == [{"left": 1, "top": 2, "width": 2, "height": 2}]
    image.close()
