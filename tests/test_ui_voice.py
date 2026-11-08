from types import SimpleNamespace
import sys

from himari import ui
from himari.ui import UI


def test_done_finishes_displaying_response_before_speech(monkeypatch):
    events = []

    class Chat:
        def append(self, text):
            events.append(("append", text))

        def ensureCursorVisible(self):
            events.append(("visible", None))

    window = SimpleNamespace(
        busy=True,
        _streamed_response="",
        chat=Chat(),
        session="test",
        _speak=lambda text: events.append(("speak", text)),
    )
    monkeypatch.setattr(ui, "load", lambda: {
        "privacy": {"store_conversations": False, "auto_memory": False},
    })
    monkeypatch.setattr(ui.db, "history", lambda *args, **kwargs: [])

    UI._done(window, "Hello there.")

    assert events[0] == ("append", "\nHimari: Hello there.")
    assert events[1] == ("visible", None)
    assert events[2] == ("speak", "Hello there.")
    assert window.busy is False


def test_screen_result_passes_extracted_text_as_model_context():
    events = []

    class Input:
        def setText(self, text):
            events.append(("input", text))

    class Button:
        def setEnabled(self, enabled):
            events.append(("button", enabled))

    class Chat:
        def append(self, text):
            events.append(("chat", text))

    window = SimpleNamespace(
        analyze_btn=Button(),
        chat=Chat(),
        input=Input(),
        isHidden=lambda: False,
        send=lambda **kwargs: events.append(("send", kwargs)),
    )

    UI._screen_result(window, "Visible error text", "What does this error mean?")

    assert ("send", {"screen_context": "Visible error text"}) in events
    assert ("input", "What does this error mean?") in events
    assert any("screenshot discarded" in message.lower() for kind, message in events if kind == "chat")


def test_screen_failure_reenables_capture_button():
    events = []
    window = SimpleNamespace(
        analyze_btn=SimpleNamespace(setEnabled=events.append),
        _status=events.append,
        isHidden=lambda: False,
    )

    UI._screen_failed(window, "Screen error")

    assert events == [True, "Screen error"]


def test_screen_result_restores_hidden_window_after_ocr():
    events = []

    class Chat:
        def append(self, text):
            events.append("append")

    window = SimpleNamespace(
        analyze_btn=SimpleNamespace(setEnabled=lambda enabled: None),
        chat=Chat(),
        input=SimpleNamespace(setText=lambda text: None),
        isHidden=lambda: True,
        show=lambda: events.append("show"),
        raise_=lambda: events.append("raise"),
        activateWindow=lambda: events.append("activate"),
        send=lambda **kwargs: events.append("send"),
    )

    UI._screen_result(window, "Captured screen text", "")

    assert events[:4] == ["show", "raise", "activate", "append"]
    assert events[-1] == "send"


def test_global_hotkeys_bind_push_to_talk_and_screen_capture(monkeypatch):
    registered = []
    emitted = []

    class SignalStub:
        def emit(self):
            emitted.append(self.name)

    ptt_signal = SignalStub()
    ptt_signal.name = "ptt"
    screen_signal = SignalStub()
    screen_signal.name = "screen"

    def add_hotkey(key, callback):
        registered.append((key, callback))
        return len(registered)

    monkeypatch.setitem(sys.modules, "keyboard", SimpleNamespace(add_hotkey=add_hotkey))
    monkeypatch.setattr(ui, "load", lambda: {
        "voice": {"push_to_talk_key": "f9"},
        "screen": {"capture_hotkey": "f10"},
    })
    window = SimpleNamespace(
        hotkey_id=None,
        screen_hotkey_id=None,
        hotkey_error=None,
        screen_hotkey_error=None,
        hotkey_pressed=ptt_signal,
        screen_hotkey_pressed=screen_signal,
        tray=None,
        capture_tray_action=None,
        _remove_hotkeys=lambda: None,
    )

    UI._bind_hotkeys(window)
    for _, callback in registered:
        callback()

    assert [key for key, _ in registered] == ["f9", "f10"]
    assert emitted == ["ptt", "screen"]
    assert window.hotkey_error is None
    assert window.screen_hotkey_error is None


def test_global_hotkeys_report_duplicate_key(monkeypatch):
    registered = []
    monkeypatch.setitem(
        sys.modules,
        "keyboard",
        SimpleNamespace(add_hotkey=lambda key, callback: registered.append(key)),
    )
    monkeypatch.setattr(ui, "load", lambda: {
        "voice": {"push_to_talk_key": "f10"},
        "screen": {"capture_hotkey": "F10"},
    })
    window = SimpleNamespace(
        hotkey_id=None,
        screen_hotkey_id=None,
        hotkey_error=None,
        screen_hotkey_error=None,
        hotkey_pressed=SimpleNamespace(emit=lambda: None),
        screen_hotkey_pressed=SimpleNamespace(emit=lambda: None),
        tray=None,
        capture_tray_action=None,
        _remove_hotkeys=lambda: None,
    )

    UI._bind_hotkeys(window)

    assert registered == ["f10"]
    assert window.screen_hotkey_id is None
    assert "must be different" in window.screen_hotkey_error
