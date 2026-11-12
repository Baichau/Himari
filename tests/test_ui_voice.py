import threading
from types import SimpleNamespace
import sys

from himari import ui
from himari.ui import UI


def test_done_finishes_displaying_response_before_speech():
    events = []

    window = SimpleNamespace(
        busy=True,
        _streamed_response="",
        _stream_message=None,
        session="test",
        _messages=[],
        _finish_generation=lambda: events.append(("buttons", None)),
        _append_message=lambda role, content: events.append(("append", role, content)),
        _persist_message=lambda role, content: events.append(("persist", role, content)),
        _render_chat=lambda force_scroll=False: events.append(("render", None)),
        _load_sessions=lambda select=None: events.append(("sessions", None)),
        _flash_expression=lambda *args, **kwargs: events.append(("flash", None)),
        _speak=lambda text: events.append(("speak", text)),
    )

    UI._done(window, "Hello there.")

    assert events.index(("append", "assistant", "Hello there.")) < events.index(("render", None))
    assert events.index(("render", None)) < events.index(("speak", "Hello there."))
    assert ("persist", "assistant", "Hello there.") in events
    assert window.busy is False
    assert window._streamed_response == ""


def test_done_reports_an_empty_model_reply_instead_of_speaking_nothing():
    events = []

    window = SimpleNamespace(
        busy=True,
        _streamed_response="",
        _stream_message=None,
        session="test",
        _messages=[],
        _finish_generation=lambda: None,
        _append_message=lambda role, content: events.append(("append", role, content)),
        _persist_message=lambda role, content: events.append(("persist", role, content)),
        _render_chat=lambda force_scroll=False: None,
        _load_sessions=lambda select=None: None,
        _flash_expression=lambda *args, **kwargs: None,
        _speak=lambda text: events.append(("speak", text)),
    )

    UI._done(window, "")

    assert events[0][0] == "append"
    assert events[0][1] == "system"
    assert "did not return a reply" in events[0][2]
    assert ("speak", "") in events
    assert ("persist", "assistant", "") not in events


def test_streamed_tokens_are_rendered_as_a_live_assistant_message():
    window = SimpleNamespace(
        busy=True,
        _streamed_response="",
        _stream_message=None,
        _status=lambda message: None,
        _schedule_render=lambda: None,
    )

    UI._token(window, "Hi")
    UI._token(window, " there")

    assert window._stream_message["role"] == "assistant"
    assert window._stream_message["content"] == "Hi there"
    assert window._stream_message["streaming"] is True


def test_tokens_arriving_after_stop_are_ignored():
    window = SimpleNamespace(
        busy=False,
        _streamed_response="kept",
        _stream_message=None,
        _status=lambda message: None,
        _schedule_render=lambda: None,
    )

    UI._token(window, " late")

    assert window._streamed_response == "kept"
    assert window._stream_message is None


def test_stop_generation_sets_the_cancellation_event():
    window = SimpleNamespace(
        busy=True,
        _cancel_event=threading.Event(),
        stop_generation_btn=SimpleNamespace(setEnabled=lambda enabled: None),
        _status=lambda message: None,
    )

    UI.stop_generation(window)

    assert window._cancel_event.is_set()


def test_cancelled_generation_keeps_the_partial_reply():
    events = []
    window = SimpleNamespace(
        busy=True,
        _streamed_response="partial reply",
        _stream_message={"role": "assistant", "content": "partial reply"},
        session="test",
        _finish_generation=lambda: None,
        _append_message=lambda role, content: events.append(("append", role, content)),
        _persist_message=lambda role, content: events.append(("persist", role, content)),
        _status=lambda message: events.append(("status", message)),
        _render_chat=lambda force_scroll=False: events.append(("render", None)),
        _load_sessions=lambda select=None: None,
        _flash_expression=lambda *args, **kwargs: None,
    )

    UI._cancelled(window, "partial reply")

    assert ("append", "assistant", "partial reply") in events
    assert ("persist", "assistant", "partial reply") in events
    assert window.busy is False
    assert window._stream_message is None


def test_voice_toggle_persists_the_spoken_reply_preference(monkeypatch):
    saved = {}
    monkeypatch.setattr(ui, "load", lambda: {"voice": {}})
    monkeypatch.setattr(ui, "save", lambda cfg: saved.update(cfg))
    window = SimpleNamespace(
        _update_voice_button=lambda enabled: None,
        tts=SimpleNamespace(stop=lambda: None),
    )

    UI._toggle_voice_replies(window, False)

    assert saved["voice"]["speak_replies"] is False


def test_screenshot_is_attached_with_a_default_question():
    events = []
    attachment = SimpleNamespace(
        ok=True, name="screen-1.png", meta={"source": "screen"}
    )

    class Input:
        def text(self):
            return ""

        def setText(self, text):
            events.append(("input", text))

        def setFocus(self):
            events.append("focus")

    window = SimpleNamespace(
        analyze_btn=SimpleNamespace(setEnabled=lambda enabled: events.append(enabled)),
        input=Input(),
        isHidden=lambda: False,
        _attachments=[],
        _refresh_attachments=lambda: events.append("refresh"),
        _status=events.append,
    )

    UI._screenshot_ready(window, attachment, "")

    assert window._attachments == [attachment]
    assert events[0] is True
    assert "refresh" in events
    assert events[2][1].startswith("What is on my screen?")
    assert any(
        isinstance(event, str) and "local vision model" in event for event in events
    )


def test_screenshot_keeps_a_typed_question():
    captured = []
    attachment = SimpleNamespace(
        ok=True, name="screen-2.png", meta={"source": "screen"}
    )
    window = SimpleNamespace(
        analyze_btn=SimpleNamespace(setEnabled=lambda enabled: None),
        input=SimpleNamespace(
            text=lambda: "Why does this error appear?",
            setText=lambda text: captured.append(text),
            setFocus=lambda: None,
        ),
        isHidden=lambda: False,
        _attachments=[],
        _refresh_attachments=lambda: None,
        _status=lambda message: None,
    )

    UI._screenshot_ready(window, attachment, "Why does this error appear?")

    assert captured == ["Why does this error appear?"]


def test_screenshot_reports_an_unreadable_capture():
    events = []
    attachment = SimpleNamespace(ok=False, error="The screenshot is empty.")
    window = SimpleNamespace(
        analyze_btn=SimpleNamespace(setEnabled=lambda enabled: events.append(enabled)),
        isHidden=lambda: False,
        _attachments=[],
        _status=events.append,
    )

    UI._screenshot_ready(window, attachment, "")

    assert window._attachments == []
    assert events == [True, "The screenshot is empty."]


def test_screen_failure_reenables_capture_button():
    events = []
    window = SimpleNamespace(
        analyze_btn=SimpleNamespace(setEnabled=events.append),
        _status=events.append,
        isHidden=lambda: False,
    )

    UI._screen_failed(window, "Screen error")

    assert events == [True, "Screen error"]


def test_screen_capture_permission_blocks_the_capture_prompt(monkeypatch):
    events = []
    monkeypatch.setattr(
        ui.QMessageBox,
        "question",
        lambda *args: (_ for _ in ()).throw(AssertionError("permission gate must run first")),
    )
    window = SimpleNamespace(
        busy=False,
        cb_screen=SimpleNamespace(isChecked=lambda: False),
        _status=events.append,
    )

    UI.screen_query(window)

    assert events == ["Screen capture is disabled in Settings."]


def test_screenshot_restores_hidden_window_after_capture():
    events = []
    attachment = SimpleNamespace(
        ok=True, name="screen-3.png", meta={"source": "screen"}
    )
    window = SimpleNamespace(
        analyze_btn=SimpleNamespace(setEnabled=lambda enabled: None),
        input=SimpleNamespace(
            text=lambda: "",
            setText=lambda text: None,
            setFocus=lambda: None,
        ),
        isHidden=lambda: True,
        show=lambda: events.append("show"),
        raise_=lambda: events.append("raise"),
        activateWindow=lambda: events.append("activate"),
        _attachments=[],
        _refresh_attachments=lambda: None,
        _status=lambda message: None,
    )

    UI._screenshot_ready(window, attachment, "")

    assert events == ["show", "raise", "activate"]


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
        _update_hotkey_labels=lambda: None,
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
        _update_hotkey_labels=lambda: None,
    )

    UI._bind_hotkeys(window)

    assert registered == ["f10"]
    assert window.screen_hotkey_id is None
    assert "must be different" in window.screen_hotkey_error


def test_first_token_stops_the_waiting_indicator(monkeypatch):
    stopped = []
    window = SimpleNamespace(
        busy=True,
        _first_token_seen=False,
        _wait_timer=SimpleNamespace(stop=lambda: stopped.append(True)),
        _streamed_response="",
        _stream_message=None,
        _status=lambda message: None,
        _schedule_render=lambda: None,
    )

    UI._token(window, "Hi")

    assert stopped == [True]
    assert window._first_token_seen is True


def test_waiting_indicator_counts_seconds_while_ollama_loads(monkeypatch):
    statuses = []
    monkeypatch.setattr(ui.time, "monotonic", lambda: 75.0)
    window = SimpleNamespace(
        busy=True,
        _first_token_seen=False,
        _wait_started=0.0,
        _wait_timer=SimpleNamespace(stop=lambda: None),
        _status=statuses.append,
        _set_avatar_state=lambda state: None,
    )

    UI._wait_tick(window)

    assert "75s" in statuses[-1]
    assert "still" in statuses[-1].lower()


def test_delete_session_removes_only_the_selected_chat(monkeypatch):
    cleared = []
    events = []
    monkeypatch.setattr(ui.QMessageBox, "question", lambda *args: ui.QMessageBox.Yes)
    monkeypatch.setattr(ui.db, "clear_session", lambda session: cleared.append(session))
    window = SimpleNamespace(
        busy=False,
        session="current",
        _messages=[],
        _stream_message=None,
        _render_chat=lambda force_scroll=False: None,
        _load_sessions=lambda select=None: events.append(select),
        _status=lambda message: events.append(message),
    )

    UI._delete_session(window, "other", "Other chat")

    assert cleared == ["other"]
    assert window.session == "current"
    assert events[0] == "current"


def test_clear_all_history_keeps_memories_and_resets_the_chat(monkeypatch):
    cleared = []
    events = []
    monkeypatch.setattr(ui.QMessageBox, "question", lambda *args: ui.QMessageBox.Yes)
    monkeypatch.setattr(ui.db, "clear_all_sessions", lambda: cleared.append(True))
    window = SimpleNamespace(
        busy=False,
        session="old",
        _messages=[{"role": "user", "content": "hello"}],
        _stream_message=None,
        _render_chat=lambda force_scroll=False: events.append("render"),
        _load_sessions=lambda select=None: events.append(("sessions", select)),
        _status=lambda message: events.append(message),
    )

    UI.clear_all_history(window)

    assert cleared == [True]
    assert window._messages == []
    assert window.session != "old"
    assert ("sessions", window.session) in events


def test_save_chat_memory_stores_selected_text(monkeypatch):
    saved = []
    monkeypatch.setattr(
        ui.QInputDialog,
        "getText",
        lambda *args, **kwargs: (kwargs.get("text") or "", True),
    )
    monkeypatch.setattr(ui.db, "memory_is_sensitive", lambda text: False)
    monkeypatch.setattr(
        ui.db,
        "add_memory",
        lambda text, source="user", approved=1: saved.append((text, source, approved)) or "id",
    )
    window = SimpleNamespace(
        chat=SimpleNamespace(selected_text=lambda callback: callback("I like tea")),
        refresh_mem=lambda: None,
        _status=lambda message: None,
    )
    window._save_chat_memory_dialog = lambda selected: UI._save_chat_memory_dialog(
        window, selected
    )

    UI.save_chat_memory(window)

    assert saved == [("I like tea", "user", 1)]


def test_save_chat_memory_refuses_a_secret(monkeypatch):
    saved = []
    warnings = []
    monkeypatch.setattr(
        ui.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("my password is hunter2", True),
    )
    monkeypatch.setattr(ui.db, "memory_is_sensitive", lambda text: True)
    monkeypatch.setattr(
        ui.db,
        "add_memory",
        lambda *args, **kwargs: saved.append(args),
    )
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *args: warnings.append(args))
    window = SimpleNamespace(
        chat=SimpleNamespace(selected_text=lambda callback: callback("")),
        refresh_mem=lambda: None,
        _status=lambda message: None,
    )
    window._save_chat_memory_dialog = lambda selected: UI._save_chat_memory_dialog(
        window, selected
    )

    UI.save_chat_memory(window)

    assert saved == []
    assert warnings


def test_retry_last_reuses_the_same_prompt_without_duplicating_it():
    events = []
    window = SimpleNamespace(
        busy=False,
        _last_user_text="hello",
        _last_screen_context=None,
        retry_btn=SimpleNamespace(setVisible=lambda visible: events.append(("retry", visible))),
        _begin_generation=lambda text, context=None, attachments=None: events.append(
            (text, context, attachments)
        ),
        _status=lambda message: events.append(message),
    )

    UI.retry_last(window)

    assert ("retry", False) in events
    assert ("hello", None, []) in events


def test_failed_reply_keeps_partial_text_and_offers_retry():
    events = []
    window = SimpleNamespace(
        busy=True,
        session="session-1",
        _streamed_response="partial reply",
        _stream_message={"role": "assistant"},
        _finish_generation=lambda: None,
        _append_message=lambda role, content: events.append((role, content)),
        retry_btn=SimpleNamespace(setVisible=lambda visible: events.append(("retry", visible))),
        _render_chat=lambda force_scroll=False: None,
        _load_sessions=lambda select=None: None,
        _status=lambda message: None,
        _flash_expression=lambda *args, **kwargs: None,
    )

    UI._failed(window, "LLM error: timed out")

    assert ("assistant", "partial reply") in events
    assert ("retry", True) in events
    assert window._streamed_response == ""
    assert window.busy is False
