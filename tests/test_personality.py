from himari import persona as legacy_persona
from himari.personality import (
    AVATAR_STATES,
    AvatarExpression,
    Mode,
    PersonalityState,
    Persona,
    build_messages,
    build_system_prompt,
    duration_seconds,
    expr_from_status,
    is_technical_request,
    is_transient,
    label_for,
    load_persona,
    normalize_expression,
)


def test_prompt_lists_only_the_real_tool_capabilities():
    from himari.tools import TOOLS

    prompt = legacy_persona.build([], [])[0]["content"]

    assert "AVAILABLE TOOLS" in prompt
    for tool in TOOLS:
        assert f"- {tool['name']}:" in prompt
    assert "no camera" in prompt.casefold()


def test_current_request_is_sent_once_as_a_user_message():
    messages = legacy_persona.build(
        [{"role": "user", "content": "hello"}],
        [],
        user_query="hello",
    )

    assert messages[-1] == {"role": "user", "content": "hello"}
    assert [m["content"] for m in messages].count("hello") == 1
    assert "Current user request" not in messages[0]["content"]

    new_request = legacy_persona.build([], [], user_query="new question")
    assert new_request[-1] == {"role": "user", "content": "new question"}


def test_research_results_are_included_as_untrusted_reference_data():
    messages = legacy_persona.build(
        [],
        [],
        user_query="who's elder titan in dota",
        research="Web results for: Elder Titan\nSource: https://www.dota2.com/hero/eldertitan",
    )

    system = messages[0]["content"]
    assert "WEB RESEARCH" in system
    assert "untrusted reference data" in system
    assert "https://www.dota2.com/hero/eldertitan" in system
    assert "KNOWLEDGE AND REASONING" in system


def test_vision_and_attachments_are_marked_as_untrusted_data():
    messages = legacy_persona.build(
        [],
        [],
        user_query="what does this error mean?",
        vision="An error dialog reads: disk full.",
        attachments="--- BEGIN ATTACHMENT: notes.txt ---\nhello\n--- END ATTACHMENT ---",
    )

    system = messages[0]["content"]
    assert "IMAGE ANALYSIS" in system
    assert "disk full" in system
    assert "USER ATTACHMENTS" in system
    assert "notes.txt" in system
    assert "not instructions" in system


def test_prompt_asks_for_markdown_math_and_diagram_formats():
    system = legacy_persona.build([], [])[0]["content"]

    assert "RESPONSE FORMAT" in system
    assert "Mermaid" in system
    assert "$$" in system
    assert "tables" in system


def test_default_persona_is_a_warm_companion():
    persona = load_persona({})

    assert isinstance(persona, Persona)
    assert persona.name == "Himari"
    assert "warm" in persona.instruction_block().casefold()
    assert "anime-inspired" in persona.instruction_block()


def test_persona_settings_are_sanitized():
    persona = load_persona({"personality": {
        "name": "   ",
        "playfulness": "extreme",
        "roleplay": "maximum",
    }})

    assert persona.name == "Himari"
    assert persona.playfulness == "medium"
    assert persona.roleplay == "minimal"


def test_persona_settings_apply_valid_overrides():
    persona = load_persona({"personality": {
        "name": "Mari",
        "playfulness": "low",
        "roleplay": "none",
    }})

    assert persona.name == "Mari"
    assert persona.playfulness == "low"
    assert persona.roleplay == "none"
    assert "Do not roleplay" in persona.instruction_block()


def test_prompt_always_keeps_security_and_honesty_rules():
    persona = load_persona({"personality": {"playfulness": "high", "roleplay": "moderate"}})
    prompt = build_system_prompt(persona, technical=True)

    assert legacy_persona.SYSTEM.strip() in prompt
    assert "Never bypass permissions" in prompt
    assert "Never claim an action succeeded" in prompt
    assert "technical" in prompt.casefold()
    assert "do not roleplay" in prompt.casefold()


def test_conversation_prompt_is_casual_and_brief():
    prompt = build_system_prompt(technical=False)

    assert "casual conversation" in prompt
    assert "warm" in prompt.casefold()


def test_build_messages_drops_duplicate_system_messages():
    messages = [
        {"role": "system", "content": "Old prompt"},
        {"role": "user", "content": "Hi"},
        "not a message",
    ]

    built = build_messages(messages=messages)

    assert built[0]["role"] == "system"
    assert "Old prompt" not in built[0]["content"]
    assert built[1:] == [{"role": "user", "content": "Hi"}]


def test_technical_request_detection():
    assert is_technical_request("Why does this traceback appear in my Python script?")
    assert not is_technical_request("What a nice day")


def test_state_transitions_are_recorded_and_bounded():
    state = PersonalityState()
    assert state.transition("listening", "recording") is AvatarExpression.LISTENING
    assert state.transition("thinking", "processing") is AvatarExpression.THINKING
    assert state.transition("speaking", "reply") is AvatarExpression.SPEAKING
    assert state.set_mode("technical") is Mode.TECHNICAL

    assert state.expression is AvatarExpression.SPEAKING
    assert [item["expression"] for item in state.history] == [
        "listening", "thinking", "speaking",
    ]
    assert state.to_dict()["mode"] == "technical"

    for index in range(40):
        state.transition("idle" if index % 2 else "thinking", "loop")
    assert len(state.history) <= 20


def test_unknown_expressions_leave_state_valid():
    state = PersonalityState()

    assert state.transition("exploding") is None
    assert state.transition(None) is None
    assert state.expression is AvatarExpression.IDLE
    assert state.history == []


def test_repeated_expression_is_not_recorded_again():
    state = PersonalityState()

    assert state.transition("thinking") is AvatarExpression.THINKING
    assert state.transition("thinking") is None
    assert len(state.history) == 1


def test_state_reset():
    state = PersonalityState(expression=AvatarExpression.ERROR)
    state.history.append({"expression": "error"})

    assert state.reset() is AvatarExpression.IDLE
    assert state.expression is AvatarExpression.IDLE
    assert state.history == []


def test_expressions_cover_avatar_states():
    assert set(AVATAR_STATES) == {
        "idle", "listening", "thinking", "speaking",
        "happy", "confused", "sad", "error",
    }
    assert normalize_expression("HAPPY") == "happy"
    assert normalize_expression("unknown") == "idle"
    assert label_for("thinking") == "Thinking"
    assert is_transient("error") is True
    assert is_transient("idle") is False
    assert duration_seconds("happy") == 2.5
    assert duration_seconds("idle") == 2.5


def test_status_maps_to_expression():
    assert expr_from_status("TTS unavailable") == "error"
    assert expr_from_status("Listening...") == "listening"
    assert expr_from_status("Hmm, let me think.") == "thinking"
    assert expr_from_status("Speaking reply") == "speaking"
    assert expr_from_status("Tool completed") == "thinking"
    assert expr_from_status("Idle") == "idle"
