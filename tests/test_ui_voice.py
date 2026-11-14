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
        _maybe_summarize=lambda: events.append(("summarize", None)),
        _flash_expression=lambda *args, **kwargs: events.append(("flash", None)),
        _speak=lambda text: events.append(("speak", text)),
    )

    UI._done(window, "Hello there.")

    assert events.index(("append", "assistant", "Hello there.")) < events.index(("render", None))
    assert events.index(("render", None)) < events.index(("speak", "Hello there."))
    assert ("persist", "assistant", "Hello there.") in events
    assert ("summarize", None) in events
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
        _maybe_summarize=lambda: None,
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


def test_starting_push_to_talk_interrupts_speech():
    stopped = []
    window = SimpleNamespace(
        mic=SimpleNamespace(rec=False, start=lambda on_silence=None: None),
        tts=SimpleNamespace(stop=lambda: stopped.append(True)),
        mic_btn=SimpleNamespace(setText=lambda text: None),
        _status=lambda message: None,
    )

    UI.toggle_mic(window)

    assert stopped == [True]


def test_wake_word_interrupts_speech_before_listening():
    stopped = []
    window = SimpleNamespace(
        _refresh_wake_word_status=lambda state: None,
        _status=lambda message: None,
        input=SimpleNamespace(setFocus=lambda: None),
        mic=SimpleNamespace(rec=False, start=lambda on_silence=None: None),
        mic_btn=SimpleNamespace(setText=lambda text: None),
        tts=SimpleNamespace(stop=lambda: stopped.append(True)),
    )

    UI._wake_word_detected(window, "Himari")

    assert stopped == [True]


def test_stop_generation_sets_the_cancellation_event():
    released = []
    window = SimpleNamespace(
        busy=True,
        _cancel_event=threading.Event(),
        stop_generation_btn=SimpleNamespace(setEnabled=lambda enabled: None),
        _status=lambda message: None,
        _release_confirmations=lambda: released.append(True),
    )

    UI.stop_generation(window)

    assert window._cancel_event.is_set()
    assert released == [True]


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


def test_memory_conflict_check_lists_pairs_without_changing_them(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        ui,
        "MemoryManager",
        lambda: SimpleNamespace(
            conflicts=lambda: [
                {
                    "first": "User likes tea.",
                    "second": "User does not like tea.",
                    "first_id": "1",
                    "second_id": "2",
                    "reason": "one memory is negated",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        ui.QMessageBox, "warning", lambda *args: warnings.append(args)
    )

    UI.check_memory_conflicts(SimpleNamespace(_status=lambda message: None))

    assert warnings
    assert "User likes tea." in warnings[0][2]
    assert "does not like tea" in warnings[0][2]
    assert "Nothing was changed automatically" in warnings[0][2]


def test_memory_conflict_check_reports_a_clean_list(monkeypatch):
    information = []
    monkeypatch.setattr(
        ui,
        "MemoryManager",
        lambda: SimpleNamespace(conflicts=lambda: []),
    )
    monkeypatch.setattr(
        ui.QMessageBox, "information", lambda *args: information.append(args)
    )

    UI.check_memory_conflicts(SimpleNamespace(_status=lambda message: None))

    assert information
    assert "No likely contradictions" in information[0][2]


def test_open_log_viewer_reuses_one_dialog(monkeypatch):
    created = []

    class FakeDialog:
        def __init__(self, parent):
            created.append(self)
            self.refresh_count = 0
            self.shown = False

        def refresh(self):
            self.refresh_count += 1

        def show(self):
            self.shown = True

        def raise_(self):
            pass

        def activateWindow(self):
            pass

    monkeypatch.setattr("himari.log_viewer.LogViewerDialog", FakeDialog)
    window = SimpleNamespace()

    UI.open_log_viewer(window)
    UI.open_log_viewer(window)

    assert len(created) == 1
    assert created[0].refresh_count == 2
    assert created[0].shown is True


def test_confirm_tool_answers_through_the_decision_slot(monkeypatch):
    from himari.security import new_decision

    class FakeBox:
        Yes = ui.QMessageBox.Yes
        No = ui.QMessageBox.No
        Question = ui.QMessageBox.Question

        def __init__(self, parent):
            pass

        def setWindowTitle(self, title):
            pass

        def setText(self, text):
            pass

        def setIcon(self, icon):
            pass

        def setStandardButtons(self, buttons):
            pass

        def setDefaultButton(self, button):
            pass

        def exec(self):
            return self.Yes

    monkeypatch.setattr(ui, "QMessageBox", FakeBox)
    result = new_decision()
    window = SimpleNamespace()

    UI._confirm_tool(
        window, ("open_url", {"url": "https://example.com"}, "Allow?", result)
    )

    assert result["allowed"] is True
    assert result["event"].is_set()
    assert window._confirm_box is None


def test_confirm_tool_ignores_a_cancelled_request(monkeypatch):
    from himari.security import new_decision, release_pending_confirmations

    monkeypatch.setattr(ui, "QMessageBox", SimpleNamespace())
    result = new_decision()
    release_pending_confirmations()

    UI._confirm_tool(
        SimpleNamespace(),
        ("open_url", {"url": "https://example.com"}, "Allow?", result),
    )

    assert result["allowed"] is False


def test_release_confirmations_rejects_an_open_dialog(monkeypatch):
    rejected = []
    released = []
    monkeypatch.setattr(
        ui, "release_pending_confirmations", lambda: released.append(True)
    )
    window = SimpleNamespace(
        _confirm_box=SimpleNamespace(reject=lambda: rejected.append(True))
    )

    UI._release_confirmations(window)

    assert rejected == [True]
    assert released == [True]


class _Checked:
    def __init__(self, checked=False):
        self.checked = checked

    def isChecked(self):
        return self.checked


class _Value:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class _Text:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text


class _Combo:
    def __init__(self, data=None, text=""):
        self._data = data
        self._text = text

    def currentData(self):
        return self._data

    def currentText(self):
        return self._text

    def count(self):
        return 1 if self._text else 0


class _Items:
    def __init__(self, *items):
        self._items = list(items)

    def count(self):
        return len(self._items)

    def item(self, index):
        return SimpleNamespace(text=lambda: self._items[index])


def _settings_window():
    window = SimpleNamespace(
        cb_store=_Checked(True),
        cb_auto_memory=_Checked(True),
        cb_memory_enabled=_Checked(True),
        cb_apps=_Checked(True),
        cb_web=_Checked(True),
        cb_research=_Checked(False),
        cb_screen=_Checked(False),
        cb_screen_control=_Checked(True),
        cb_active_window=_Checked(False),
        cb_media=_Checked(False),
        cb_browser=_Checked(False),
        cb_write=_Checked(False),
        cb_vision=_Checked(True),
        cb_wake=_Checked(True),
        cb_preload=_Checked(True),
        cb_deep_reasoning=_Checked(True),
        cb_always_on_top=_Checked(False),
        cb_minimize_to_tray=_Checked(True),
        cb_weather_auto=_Checked(True),
        cb_auto_escalate=_Checked(True),
        cb_watch_mode=_Checked(False),
        cb_diagnostics=_Checked(True),
        cb_vscode_state=_Checked(True),
        cb_run_tests=_Checked(False),
        allowed_folders=_Items("C:/Docs"),
        development_workspaces=_Items("C:/Code"),
        reply_wait=_Value(900),
        vol=_Value(70),
        sensitivity=_Value(75),
        voice_btn=_Checked(True),
        mic_box=_Combo(data=2),
        out_box=_Combo(data=4),
        lang_box=_Combo(data="en"),
        voice_box=_Combo(text="en_US-amy-medium"),
        chat_engine_box=_Combo(data="web"),
        vision_model_box=_Combo(text="qwen2.5vl:3b"),
        model_box=_Combo(text="qwen3:8b"),
        screen_area=_Combo(data="primary"),
        weather_units=_Combo(data="metric"),
        reasoning_profile=_Combo(data="auto"),
        reasoning_rounds=_Value(12),
        calendar_duration=_Value(60),
        watch_interval=_Value(20),
        watch_cap=_Value(30),
        _screen_region=None,
        ollama_host=_Text("http://127.0.0.1:11434"),
        embedding_model=_Text("nomic-embed-text"),
        spotify_client_id=_Text("client-abc"),
        spotify_secret=_Text("secret-xyz"),
        weather_city=_Text("Tashkent"),
        hotkey=_Text("f9"),
        wake_word_field=_Text("Himari"),
        screen_hotkey=_Text("f10"),
        _recognition_language=lambda: "en",
    )
    window._settings_updates = lambda **kwargs: UI._settings_updates(window, **kwargs)
    window._save_settings = lambda **kwargs: UI._save_settings(window, **kwargs)
    window._status = lambda message: None
    return window


def test_settings_updates_include_text_fields_for_a_full_save():
    updates = UI._settings_updates(_settings_window())

    assert updates["ollama"]["host"] == "http://127.0.0.1:11434"
    assert updates["ollama"]["chat_model"] == "qwen3:8b"
    assert updates["ollama"]["vision_model"] == "qwen2.5vl:3b"
    assert updates["permissions"]["allow_screen_control"] is True
    assert updates["voice"]["push_to_talk_key"] == "f9"
    assert updates["voice"]["wake_word"] == "Himari"
    assert updates["voice"]["tts_voice"] == "en_US-amy-medium"
    assert updates["memory"]["embedding_model"] == "nomic-embed-text"
    assert updates["screen"]["capture_hotkey"] == "f10"
    assert updates["screen"]["monitor"] == "primary"
    assert updates["screen"]["region"] is None
    assert updates["permissions"]["allow_run_command"] is False
    assert updates["permissions"]["allow_watch_mode"] is False
    assert updates["permissions"]["allow_system_diagnostics"] is True
    assert updates["permissions"]["allow_vscode_state"] is True
    assert updates["permissions"]["allow_run_tests"] is False
    assert updates["screen"]["watch_interval_seconds"] == 20
    assert updates["screen"]["watch_max_minutes"] == 30
    assert updates["spotify"]["client_id"] == "client-abc"
    assert updates["spotify"]["client_secret"] == "secret-xyz"
    assert updates["location"]["city"] == "Tashkent"
    assert updates["location"]["units"] == "metric"
    assert updates["reasoning"]["profile"] == "auto"
    assert updates["reasoning"]["max_rounds"] == 12
    assert updates["calendar"]["default_duration_minutes"] == 60


def test_settings_autosave_skips_partially_typed_text_fields():
    updates = UI._settings_updates(_settings_window(), text_fields=False)

    assert "host" not in updates["ollama"]
    assert "chat_model" not in updates["ollama"]
    assert "vision_model" not in updates["ollama"]
    assert "push_to_talk_key" not in updates["voice"]
    assert "wake_word" not in updates["voice"]
    assert "capture_hotkey" not in updates["screen"]
    assert updates["screen"]["monitor"] == "primary"
    assert updates["screen"]["region"] is None
    assert "memory" not in updates
    assert "imagegen" not in updates
    assert "spotify" not in updates
    assert "city" not in updates["location"]
    assert updates["location"]["auto_detect"] is True
    assert updates["reasoning"]["auto_escalate"] is True
    assert updates["calendar"]["default_duration_minutes"] == 60
    assert updates["ui"]["chat_engine"] == "web"
    assert updates["voice"]["volume"] == 0.7
    assert updates["voice"]["sensitivity"] == 0.75
    assert updates["voice"]["microphone_device"] == 2
    assert updates["voice"]["output_device"] == 4
    assert updates["voice"]["tts_voice"] == "en_US-amy-medium"
    assert updates["permissions"]["allowed_folders"] == ["C:/Docs"]


def test_full_save_and_autosave_both_use_the_validated_service(monkeypatch):
    calls = []

    class FakeService:
        def update(self, updates):
            calls.append(updates)
            return {}

    monkeypatch.setattr(ui.control_settings, "SettingsService", FakeService)
    window = _settings_window()

    assert UI._save_settings(window, interactive=True) is True
    assert UI._save_settings(window, interactive=False) is True

    assert "host" in calls[0]["ollama"]
    assert "screen" in calls[0]
    assert calls[0]["screen"]["capture_hotkey"] == "f10"
    assert "host" not in calls[1]["ollama"]
    assert "capture_hotkey" not in calls[1]["screen"]
    assert calls[1]["screen"]["monitor"] == "primary"


def test_autosave_failure_warns_once_without_a_dialog(monkeypatch):
    warnings = []
    statuses = []

    class BrokenService:
        def update(self, updates):
            raise ui.control_settings.SettingsError("Invalid value for voice.volume")

    monkeypatch.setattr(ui.control_settings, "SettingsService", BrokenService)
    monkeypatch.setattr(
        ui.QMessageBox, "warning", lambda *args: warnings.append(args)
    )
    window = _settings_window()
    window._status = statuses.append

    assert UI._autosave_settings(window) is None
    assert warnings == []
    assert len(statuses) == 1
    assert "could not be saved" in statuses[0]

    UI._autosave_settings(window)
    assert len(statuses) == 1


def test_settings_save_skips_reads_from_destroyed_widgets(monkeypatch):
    calls = []

    class FakeService:
        def update(self, updates):
            calls.append(updates)
            return {}

    def deleted(**_kwargs):
        raise RuntimeError(
            "Internal C++ object (PySide6.QtWidgets.QPushButton) already deleted."
        )

    monkeypatch.setattr(ui.control_settings, "SettingsService", FakeService)
    window = SimpleNamespace(
        _settings_updates=deleted,
        _settings_save_warned=False,
    )
    window._save_settings = lambda **kwargs: UI._save_settings(window, **kwargs)

    assert UI._save_settings(window, interactive=True) is False
    assert calls == []


def test_autosave_debounce_timer_is_started_by_widget_changes():
    started = []
    window = SimpleNamespace(
        _settings_save_timer=SimpleNamespace(start=lambda: started.append(True)),
    )

    UI._schedule_settings_save(window)
    UI._schedule_settings_save(window, False)

    assert len(started) == 2


def test_voice_poll_drives_both_waveforms_from_real_state():
    modes = []
    wave = SimpleNamespace(
        set_mode=lambda mode: modes.append(mode),
        set_level=lambda level: modes.append(level),
    )
    companion = SimpleNamespace(
        set_mode=lambda mode: modes.append(mode),
        set_level=lambda level: modes.append(level),
    )
    timers = []
    window = SimpleNamespace(
        voice_wave=wave,
        companion_wave=companion,
        mic=SimpleNamespace(rec=True, level=0.42),
        _tts_active=False,
        _voice_timer=SimpleNamespace(stop=lambda: timers.append("stop")),
    )

    UI._poll_voice(window)

    assert modes.count("listening") == 2
    assert 0.42 in modes
    assert timers == []

    window.mic = SimpleNamespace(rec=False, level=0.0)
    UI._poll_voice(window)
    assert modes.count("idle") == 2
    assert timers == ["stop"]


def test_finished_tts_marks_speech_inactive_and_reports_ready():
    statuses = []
    window = SimpleNamespace(
        _tts_active=True,
        busy=False,
        status=SimpleNamespace(emit=statuses.append),
    )

    UI._on_tts_finished(window)

    assert window._tts_active is False
    assert statuses == ["Ready."]
