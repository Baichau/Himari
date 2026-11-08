from types import SimpleNamespace

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
    )

    UI._screen_failed(window, "Screen error")

    assert events == [True, "Screen error"]
