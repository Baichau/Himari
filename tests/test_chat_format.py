from himari.chat_format import markdown_to_html, render_messages_html, welcome_html


def test_markdown_escapes_html_before_formatting():
    rendered = markdown_to_html("<script>alert('x')</script>")

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_markdown_renders_fenced_code_and_inline_code():
    rendered = markdown_to_html("```python\nprint('hi')\n```\nUse `pip install` next.")

    assert "PYTHON" in rendered
    assert "print(&#x27;hi&#x27;)" in rendered
    assert "Consolas" in rendered


def test_markdown_links_only_http_urls():
    rendered = markdown_to_html("See [docs](https://example.com/a) and www.bad.example")

    assert '<a href="https://example.com/a"' in rendered
    assert 'href="www.bad.example"' not in rendered


def test_markdown_formats_headings_bullets_and_emphasis():
    rendered = markdown_to_html("# Title\n- item\n**bold** and *italic*")

    assert "font-size:17px" in rendered
    assert "• item" in rendered
    assert "<b>bold</b>" in rendered
    assert "<i>italic</i>" in rendered


def test_empty_transcript_shows_the_welcome_card():
    rendered = render_messages_html([])

    assert "Hey, I'm Himari." in rendered
    assert "What is my active window?" in rendered


def test_empty_transcript_can_render_nothing():
    assert render_messages_html([], empty=False) == ""


def test_tool_messages_are_hidden_until_requested():
    messages = [
        {"role": "user", "content": "Open Spotify", "ts": 0},
        {"role": "tool", "content": "open_app → launched", "ts": 0},
        {"role": "assistant", "content": "Done.", "ts": 0},
    ]

    hidden = render_messages_html(messages)
    visible = render_messages_html(messages, show_tools=True)

    assert "open_app" not in hidden
    assert "open_app" in visible
    assert "YOU" in hidden and "HIMARI" in hidden


def test_streaming_assistant_message_gets_a_cursor():
    rendered = render_messages_html([
        {"role": "assistant", "content": "Thinking", "streaming": True},
    ])

    assert "Thinking" in rendered
    assert "▍" in rendered


def test_welcome_uses_the_configured_name():
    assert "Mari" in welcome_html("Mari")
