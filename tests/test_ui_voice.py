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
