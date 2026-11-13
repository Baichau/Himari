from types import SimpleNamespace

import pytest

from himari.windows import input as wininput
from himari.windows import uia
from himari.windows.input import ScreenInputError
from himari.windows.uia import ScreenControlError


class FakeUser32:
    def __init__(self, left=0, top=0, width=1920, height=1080):
        self.metrics = {
            wininput.SM_XVIRTUALSCREEN: left,
            wininput.SM_YVIRTUALSCREEN: top,
            wininput.SM_CXVIRTUALSCREEN: width,
            wininput.SM_CYVIRTUALSCREEN: height,
        }

    def GetSystemMetrics(self, index):
        return self.metrics.get(index, 0)


@pytest.fixture()
def sent(monkeypatch):
    events = []
    monkeypatch.setattr(wininput, "_send", events.extend)
    monkeypatch.setattr(wininput, "_api", lambda: FakeUser32())
    return events


def test_parse_keys_maps_names_and_modifiers():
    assert wininput.parse_keys("ctrl+shift+s") == [0x11, 0x10, 0x53]
    assert wininput.parse_keys("Enter") == [0x0D]
    assert wininput.parse_keys("f5") == [0x74]


def test_parse_keys_refuses_unknown_empty_and_windows_keys():
    with pytest.raises(ScreenInputError):
        wininput.parse_keys("")
    with pytest.raises(ScreenInputError):
        wininput.parse_keys("ctrl+")
    with pytest.raises(ScreenInputError):
        wininput.parse_keys("win+r")
    with pytest.raises(ScreenInputError):
        wininput.parse_keys("launch")
    with pytest.raises(ScreenInputError):
        wininput.parse_keys("+".join(["ctrl"] * 9))


def test_type_text_sends_unicode_events_and_enter(sent):
    wininput.type_text("Hi\n")

    kinds = [event.ki.wScan for event in sent]
    assert kinds[:2] == [ord("H"), ord("H")]
    assert kinds[2:4] == [ord("i"), ord("i")]
    assert [event.ki.wVk for event in sent[4:6]] == [0x0D, 0x0D]
    assert sent[1].ki.dwFlags & wininput.KEYEVENTF_KEYUP


def test_type_text_rejects_empty_long_and_null_text():
    with pytest.raises(ScreenInputError):
        wininput.type_text("")
    with pytest.raises(ScreenInputError):
        wininput.type_text("x" * (wininput.MAX_TEXT + 1))
    with pytest.raises(ScreenInputError):
        wininput.type_text("a\x00b")


def test_press_keys_holds_modifiers_around_the_key(sent):
    wininput.press_keys("ctrl+s")

    assert [(event.ki.wVk, event.ki.dwFlags) for event in sent] == [
        (0x11, 0),
        (0x53, 0),
        (0x53, wininput.KEYEVENTF_KEYUP),
        (0x11, wininput.KEYEVENTF_KEYUP),
    ]


def test_click_at_rejects_points_outside_the_desktop(sent):
    wininput.click_at(10, 10)
    with pytest.raises(ScreenInputError):
        wininput.click_at(5000, 10)
    with pytest.raises(ScreenInputError):
        wininput.click_at(-1, 10)


def test_click_at_limits_click_count_and_button(sent):
    with pytest.raises(ScreenInputError):
        wininput.click_at(10, 10, clicks=3)
    with pytest.raises(ScreenInputError):
        wininput.click_at(10, 10, button="side")


def test_scroll_limits_amount_and_requires_both_coordinates(sent):
    with pytest.raises(ScreenInputError):
        wininput.scroll_screen(0)
    with pytest.raises(ScreenInputError):
        wininput.scroll_screen(25)
    with pytest.raises(ScreenInputError):
        wininput.scroll_screen(1, x=10)
    wininput.scroll_screen(-2)
    assert sent[-1].mi.mouseData == (2**32 - 2 * wininput.WHEEL_DELTA)


class FakeElementInfo:
    def __init__(self, name, control_type, automation_id="", password=False):
        self.name = name
        self.control_type = control_type
        self.automation_id = automation_id
        self.process_id = 999999
        self.element = SimpleNamespace(CurrentIsPassword=password)


class FakeControl:
    def __init__(self, name, control_type="Button", automation_id="", password=False):
        self.element_info = FakeElementInfo(name, control_type, automation_id, password)
        self.clicked = 0
        self.invoked = 0
        self.focused = 0
        self.text = None

    def is_enabled(self):
        return True

    def is_visible(self):
        return True

    def click_input(self):
        self.clicked += 1

    def invoke(self):
        self.invoked += 1

    def set_focus(self):
        self.focused += 1

    def set_edit_text(self, text):
        self.text = text


class FakeWindow:
    def __init__(self, title, controls=(), handle=0):
        self.title = title
        self.controls = list(controls)
        self.handle = handle
        self.focused = 0
        self.element_info = SimpleNamespace(process_id=999999)

    def is_visible(self):
        return True

    def window_text(self):
        return self.title

    def descendants(self):
        return self.controls

    def set_focus(self):
        self.focused += 1


class FakeDesktop:
    def __init__(self, windows):
        self._windows = windows

    def windows(self):
        return self._windows


@pytest.fixture()
def desktop(monkeypatch):
    windows = [
        FakeWindow("Notepad", [
            FakeControl("Save", "Button"),
            FakeControl("Search", "Edit"),
            FakeControl("Password", "Edit", password=True),
        ], handle=101),
        FakeWindow("Untitled - Notepad", [FakeControl("Close", "Button")], handle=202),
    ]
    monkeypatch.setattr(uia, "_desktop", lambda: FakeDesktop(windows))
    return windows


def test_find_window_prefers_exact_then_substring(desktop):
    assert uia.find_window("Notepad").title == "Notepad"
    assert uia.find_window("untitled").title == "Untitled - Notepad"


def test_find_window_active_targets_the_foreground_window(desktop, monkeypatch):
    monkeypatch.setattr(uia, "_foreground_hwnd", lambda: 202)
    assert uia.find_window("active").title == "Untitled - Notepad"
    assert uia.find_window("foreground").title == "Untitled - Notepad"

    result = uia.list_controls("active")
    assert [item["name"] for item in result["controls"]] == ["Close"]
    assert desktop[1].focused == 0


def test_find_window_active_reports_missing_or_hidden_foreground(desktop, monkeypatch):
    monkeypatch.setattr(uia, "_foreground_hwnd", lambda: 0)
    with pytest.raises(ScreenControlError, match="no active window"):
        uia.find_window("active")

    monkeypatch.setattr(uia, "_foreground_hwnd", lambda: 999)
    with pytest.raises(ScreenControlError, match="not available"):
        uia.find_window("active")


def test_find_window_refuses_ambiguity_and_reports_unknown(monkeypatch):
    monkeypatch.setattr(
        uia,
        "_desktop",
        lambda: FakeDesktop([FakeWindow("A - Notepad"), FakeWindow("B - Notepad")]),
    )
    with pytest.raises(ScreenControlError, match="windows match"):
        uia.find_window("notepad")
    with pytest.raises(ScreenControlError, match="No open window"):
        uia.find_window("spotify")


def test_list_controls_is_read_only_and_filterable(desktop):
    result = uia.list_controls("Notepad")
    assert result["count"] == 3
    assert [item["name"] for item in result["controls"]] == ["Save", "Search", "Password"]
    assert desktop[0].focused == 0

    filtered = uia.list_controls("Notepad", name_filter="edit")
    assert [item["name"] for item in filtered["controls"]] == ["Search", "Password"]


def test_click_control_uses_a_unique_match(desktop):
    result = uia.click_control("Notepad", "save")
    assert "Clicked Save (Button)" in result
    assert desktop[0].controls[0].clicked == 1
    assert desktop[0].focused == 1


def test_click_control_refuses_duplicate_names(desktop):
    desktop[0].controls.append(FakeControl("Save", "MenuItem"))
    with pytest.raises(ScreenControlError, match="controls match"):
        uia.click_control("Notepad", "Save")
    assert desktop[0].controls[0].clicked == 0


def test_click_control_falls_back_to_invoke(desktop):
    class InvokeOnly(FakeControl):
        def click_input(self):
            raise RuntimeError("no pointer")

    control = InvokeOnly("Save", "Button")
    desktop[0].controls[0] = control
    result = uia.click_control("Notepad", "Save")
    assert control.invoked == 1
    assert "UI Automation" in result


def test_set_control_text_replaces_an_edit_field(desktop):
    result = uia.set_control_text("Notepad", "search", "hello")
    assert desktop[0].controls[1].text == "hello"
    assert "Typed into" not in result


def test_set_control_text_refuses_password_fields(desktop, monkeypatch):
    monkeypatch.setattr(uia, "_looks_password", lambda control: True)
    with pytest.raises(ScreenControlError, match="password"):
        uia.set_control_text("Notepad", "search", "hunter2")


def test_list_controls_requires_a_window_name():
    with pytest.raises(ScreenControlError):
        uia.list_controls("")


def test_screen_control_tools_fail_closed_without_permission(monkeypatch):
    from himari import tools

    monkeypatch.setattr(tools, "_perm", lambda key: False)
    assert tools.list_controls_tool("Notepad").startswith("Permission denied")
    assert tools.click_control_tool("Notepad", "Save").startswith("Permission denied")
    assert tools.type_text_tool("hello").startswith("Permission denied")
    assert tools.press_keys_tool("ctrl+s").startswith("Permission denied")
    assert tools.click_at_tool(10, 10).startswith("Permission denied")
    assert tools.scroll_screen_tool(-1).startswith("Permission denied")
