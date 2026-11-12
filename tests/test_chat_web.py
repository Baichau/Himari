from pathlib import Path
from types import SimpleNamespace

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


def test_streaming_message_has_a_cursor():
    rendered = chat_web.render_messages_html(
        [{"role": "assistant", "content": "thinking", "streaming": True}]
    )

    assert 'class="cursor"' in rendered


def test_tool_messages_follow_the_show_tools_flag():
    messages = [{"role": "tool", "content": "open_app({})"}]

    hidden = chat_web.render_messages_html(messages)
    visible = chat_web.render_messages_html(messages, show_tools=True)

    assert "open_app" not in hidden
    assert "open_app" in visible
    assert 'class="tool"' in visible


def test_empty_transcript_shows_a_welcome_screen():
    rendered = chat_web.render_messages_html([])

    assert 'class="welcome"' in rendered
    assert "Himari" in rendered


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
