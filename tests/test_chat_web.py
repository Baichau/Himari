from pathlib import Path
from types import SimpleNamespace

import pytest

from himari import chat_web
from himari.attachments import Attachment


def test_markdown_covers_bold_tables_and_lists():
    rendered = chat_web.markdown_to_html(
        "**Bold** text\n\n| Item | Cost |\n|---|---|\n| Rent | 900 |\n\n- one\n- two"
    )

    assert "<strong>Bold</strong>" in rendered
    assert "<table>" in rendered and "<th>Cost</th>" in rendered
    assert "<li>one</li>" in rendered


def test_math_is_stashed_before_markdown_and_restored():
    rendered = chat_web.markdown_to_html(
        r"Inline $a^2 + b^2$ and display: $$\frac{x}{y}$$"
    )

    assert '<span class="math" data-display="0">a^2 + b^2</span>' in rendered
    assert '<span class="math" data-display="1">\\frac{x}{y}</span>' in rendered
    assert "$" not in rendered


def test_bracket_math_is_supported():
    rendered = chat_web.markdown_to_html(r"\[ E = mc^2 \] and \(x_1\)")

    assert 'data-display="1">E = mc^2<' in rendered
    assert 'data-display="0">x_1<' in rendered


def test_mermaid_fences_become_diagram_blocks():
    rendered = chat_web.markdown_to_html(
        "```mermaid\nflowchart TD\nA --> B\n```"
    )

    assert '<div class="mermaid-wrap">' in rendered
    assert '<pre class="mermaid">flowchart TD\nA --&gt; B</pre>' in rendered
    assert "<p><div" not in rendered


def test_model_html_and_scripts_are_escaped():
    rendered = chat_web.markdown_to_html(
        "<script>alert('x')</script><img src=x onerror=alert(1)>"
    )

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<img" not in rendered


def test_markdown_images_are_reduced_to_alt_text():
    rendered = chat_web.markdown_to_html("![a cat](https://example.com/cat.png)")

    assert "<img" not in rendered
    assert "[image: a cat]" in rendered


def test_messages_include_attachment_chips_and_generated_images(tmp_path):
    picture = tmp_path / "generated.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n")
    attachment = Attachment(
        name="budget.xlsx",
        kind="sheet",
        thumbnail="data:image/png;base64,AAAA",
    )

    rendered = chat_web.render_messages_html(
        [
            {"role": "user", "content": "read this", "attachments": [attachment]},
            {"role": "assistant", "content": "Done", "image": str(picture)},
        ]
    )

    assert 'class="chip"' in rendered
    assert "budget.xlsx" in rendered
    assert 'class="generated"' in rendered
    assert picture.resolve().as_uri() in rendered


def test_streaming_message_has_a_cursor_and_typing_dots():
    rendered = chat_web.render_messages_html(
        [{"role": "assistant", "content": "thinking", "streaming": True}]
    )

    assert 'class="cursor"' in rendered
    assert 'class="typing"' in rendered
    assert rendered.count("<i></i>") == 3


def test_only_assistant_messages_show_the_small_avatar_badge():
    assistant = chat_web.render_message_html(
        {"role": "assistant", "content": "Hello"}
    )
    user = chat_web.render_message_html({"role": "user", "content": "Hi"})

    assert 'class="avatar-badge"' in assistant
    assert 'class="avatar-badge"' not in user


def test_tool_messages_follow_the_show_tools_flag():
    messages = [{"role": "tool", "content": "open_app({})"}]

    hidden = chat_web.render_messages_html(messages)
    visible = chat_web.render_messages_html(messages, show_tools=True)

    assert "open_app" not in hidden
    assert "open_app" in visible
    assert 'class="tool"' in visible


def test_failed_tool_messages_are_marked_in_the_transcript():
    failed = chat_web.render_messages_html(
        [{"role": "tool", "content": "Denied: not allowed"}],
        show_tools=True,
    )
    succeeded = chat_web.render_messages_html(
        [{"role": "tool", "content": "Chrome is open."}],
        show_tools=True,
    )

    assert 'class="tool tool-failed"' in failed
    assert "FAILED" in failed
    assert "tool-failed" not in succeeded


def test_message_cards_carry_copy_text_and_a_copy_button():
    rendered = chat_web.render_message_html(
        {"role": "assistant", "content": 'say "hello" <b>now</b>'}
    )

    assert 'class="copy-msg"' in rendered
    assert (
        'data-copy="say &quot;hello&quot; &lt;b&gt;now&lt;/b&gt;"' in rendered
    )


def test_messages_without_text_have_no_copy_controls():
    rendered = chat_web.render_message_html(
        {"role": "assistant", "content": "", "image": "C:/tmp/pic.png"}
    )

    assert "copy-msg" not in rendered
    assert 'class="generated"' in rendered


def test_shell_styles_code_blocks_and_syntax_tokens():
    shell = chat_web.shell_html(font_size=14, theme_name="dark")

    assert ".code-block" in shell
    assert ".copy-code" in shell
    assert ".tok-kw" in shell
    assert ".tok-str" in shell


def test_copy_prompt_bridge_emits_the_text_and_refuses_other_prompts():
    page_class = getattr(chat_web, "_ChatPage", None)
    if page_class is None:
        pytest.skip("QtWebEngine is unavailable")

    class _Signal:
        def __init__(self):
            self.values = []

        def emit(self, value):
            self.values.append(value)

    fake = SimpleNamespace(copyRequested=_Signal())

    result = page_class.javaScriptPrompt(fake, "", "himari-copy", "print(1)\n")
    refused = page_class.javaScriptPrompt(fake, "", "something else", "x")

    assert result == (True, "1")
    assert fake.copyRequested.values == ["print(1)\n"]
    assert refused == (False, "")
    assert fake.copyRequested.values == ["print(1)\n"]


def test_fill_prompt_bridge_emits_the_welcome_suggestion():
    page_class = getattr(chat_web, "_ChatPage", None)
    if page_class is None:
        pytest.skip("QtWebEngine is unavailable")

    class _Signal:
        def __init__(self):
            self.values = []

        def emit(self, value):
            self.values.append(value)

    fake = SimpleNamespace(fillRequested=_Signal())

    result = page_class.javaScriptPrompt(fake, "", "himari-fill", "Open a fireplace video")

    assert result == (True, "1")
    assert fake.fillRequested.values == ["Open a fireplace video"]


def test_empty_transcript_shows_a_welcome_screen():
    rendered = chat_web.render_messages_html([])

    assert 'class="welcome"' in rendered
    assert "Himari" in rendered
    assert 'class="welcome-chips"' in rendered
    assert 'data-prompt="' in rendered
    assert "first reply after launch" in rendered


def test_welcome_chips_are_clickable_buttons_without_image_generation():
    rendered = chat_web.render_messages_html([])

    assert '<button type="button" data-prompt="' in rendered
    assert "Draw me a picture" not in rendered
    assert "mind map" in rendered.casefold()


def test_first_streaming_render_is_a_full_render():
    payload, count, streaming = chat_web.build_render_payload(
        [{"role": "assistant", "content": "Hel", "streaming": True}]
    )

    assert "html" in payload and "last" not in payload
    assert 'class="cursor"' in payload["html"]
    assert payload["streaming"] is True
    assert count == 1 and streaming is True


def test_repeated_streaming_render_sends_only_the_last_card():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hel", "streaming": True},
    ]

    payload, count, streaming = chat_web.build_render_payload(
        messages,
        rendered_count=2,
        rendered_streaming=True,
    )

    assert "last" in payload and "html" not in payload
    assert "Hel" in payload["last"]
    assert "hi" not in payload["last"]
    assert count == 2 and streaming is True


def test_final_render_after_streaming_is_full_and_drops_the_cursor():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello there"},
    ]

    payload, count, streaming = chat_web.build_render_payload(
        messages,
        rendered_count=2,
        rendered_streaming=True,
    )

    assert "html" in payload and "last" not in payload
    assert 'class="cursor"' not in payload["html"]
    assert "Hello there" in payload["html"]
    assert count == 2 and streaming is False


def test_tool_toggle_changes_the_count_and_forces_a_full_render():
    messages = [
        {"role": "assistant", "content": "Hel", "streaming": True},
        {"role": "tool", "content": "open_app({})"},
    ]

    hidden_payload, hidden_count, _ = chat_web.build_render_payload(
        messages,
        rendered_count=1,
        rendered_streaming=True,
    )
    visible_payload, visible_count, _ = chat_web.build_render_payload(
        messages,
        show_tools=True,
        rendered_count=1,
        rendered_streaming=True,
    )

    assert hidden_count == 1 and "last" in hidden_payload
    assert visible_count == 2
    assert "html" in visible_payload and "last" not in visible_payload
    assert 'class="tool"' in visible_payload["html"]


def test_incremental_render_requires_the_streaming_card_to_be_last():
    messages = [
        {"role": "assistant", "content": "Hel", "streaming": True},
        {"role": "system", "content": "note"},
    ]

    payload, count, _ = chat_web.build_render_payload(
        messages,
        rendered_count=2,
        rendered_streaming=True,
    )

    assert count == 2
    assert "html" in payload and "last" not in payload


def test_role_cards_escape_untrusted_names():
    rendered = chat_web.render_messages_html(
        [{"role": "user", "content": "hi"}],
        assistant_name="<b>Himari</b>",
    )

    assert "<b>Himari</b>" not in rendered


def test_shell_locks_the_page_down_and_uses_bundled_assets():
    shell = chat_web.shell_html(font_size=14, theme_name="dark")

    assert "Content-Security-Policy" in shell
    assert "script-src 'self'" in shell
    assert "katex/katex.min.css" in shell
    assert "mermaid.min.js" in shell
    assert "himari-chat.js" in shell
    assert "connect-src 'none'" in shell


def test_bundled_assets_exist():
    assets = chat_web.ASSETS_DIR

    for relative in (
        "katex/katex.min.js",
        "katex/katex.min.css",
        "mermaid.min.js",
        "himari-chat.js",
    ):
        assert (Path(assets) / relative).is_file(), relative


def test_transcript_scroll_survives_long_restores():
    # A long smooth scroll leaves the embedded view unpainted, which reads as
    # an empty transcript, so big jumps must be instant and content growth must
    # keep the pinned transcript at the bottom.
    script = (Path(chat_web.ASSETS_DIR) / "himari-chat.js").read_text(encoding="utf-8")

    assert "distance < 600" in script
    assert "new ResizeObserver" in script
    assert "window.scrollTo(0, document.documentElement.scrollHeight)" in script


def test_classic_renderer_includes_attachment_names_and_image_path():
    attachment = SimpleNamespace(name="notes.txt")
    rendered = chat_web.chat_format.render_messages_html(
        [
            {"role": "user", "content": "look", "attachments": [attachment]},
            {"role": "assistant", "content": "", "image": "C:/tmp/pic.png"},
        ]
    )

    assert "Attached: notes.txt" in rendered
    assert "Generated image saved to C:/tmp/pic.png" in rendered
