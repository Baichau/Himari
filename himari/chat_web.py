"""Rich chat transcript rendering.

The primary view embeds QtWebEngine and renders Markdown, KaTeX formulas, and
Mermaid diagrams with assets that ship inside the app. A QTextBrowser view is
kept as a fallback for machines where QtWebEngine cannot start.

Model text never reaches the page as HTML: it is escaped by markdown-it before
rendering, raw HTML is disabled, images are reduced to alt text, and the page
runs under a strict Content-Security-Policy with scripts loaded only from the
bundled asset folder.
"""

import base64
import html
import json
import logging
import re
import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import QApplication, QTextBrowser

from . import chat_format
from .theme import palette as theme_palette
from .tool_results import classify_result

log = logging.getLogger("himari.chat_web")

ASSETS_DIR = Path(__file__).resolve().parent / "web_assets"


# ---- Markdown, math and diagram preparation -------------------------------

_MATH_DISPLAY_DOLLAR = re.compile(r"\$\$(.+?)\$\$", re.S)
_MATH_DISPLAY_BRACKET = re.compile(r"\\\[(.+?)\\\]", re.S)
_MATH_INLINE_PAREN = re.compile(r"\\\((.+?)\\\)", re.S)
_MATH_INLINE_DOLLAR = re.compile(
    r"(?<![\\$])\$(?![\s$])((?:\\.|[^$\\\n])+?)(?<![\s\\])\$(?!\$)"
)
_MERMAID_FENCE = re.compile(r"```mermaid[ \t]*\r?\n(.*?)```", re.S)
_PLACEHOLDER = re.compile(r"@@(MATH|MERMAID)(\d+)@@")

_md = None


def _markdown():
    global _md
    if _md is not None:
        return _md
    try:
        from markdown_it import MarkdownIt
    except Exception as exc:  # pragma: no cover - dependency is bundled
        log.warning("markdown-it-py unavailable, using the classic renderer: %s", exc)
        return None
    md = MarkdownIt(
        "commonmark",
        {"html": False, "breaks": True, "linkify": False, "typographer": False},
    )
    for rule in ("table", "strikethrough"):
        try:
            md.enable(rule)
        except Exception:  # pragma: no cover - rule set changes between releases
            pass

    def render_image(tokens, idx, options, env):
        token = tokens[idx]
        alt = str(getattr(token, "content", "") or "").strip()
        label = f"[image: {html.escape(alt)}]" if alt else "[image]"
        return f'<span class="img-alt">{label}</span>'

    try:
        md.renderer.rules["image"] = render_image
    except Exception:  # pragma: no cover
        pass
    _md = md
    return _md


def _stash(store, kind, value):
    store.append((kind, value))
    return f"@@{kind}{len(store) - 1}@@"


def _restore(fragment, store):
    def replace(match):
        kind, index = match.group(1), int(match.group(2))
        if index >= len(store):
            return ""
        stored_kind, value = store[index]
        if stored_kind == "MATH":
            display = value[0]
            latex = html.escape(value[1], quote=False)
            return (
                f'<span class="math" data-display="{"1" if display else "0"}">'
                f"{latex}</span>"
            )
        if stored_kind == "MERMAID":
            return (
                '<div class="mermaid-wrap"><pre class="mermaid">'
                f"{html.escape(value, quote=False)}</pre></div>"
            )
        return ""

    return _PLACEHOLDER.sub(replace, fragment)


def markdown_to_html(text):
    """Convert model Markdown into safe HTML with math and diagram hooks."""
    source = str(text or "")
    stash = []

    def keep_math(display):
        def repl(match):
            body = match.group(1).strip()
            if not body:
                return match.group(0)
            return _stash(stash, "MATH", (display, body))

        return repl

    source = _MATH_DISPLAY_DOLLAR.sub(keep_math(True), source)
    source = _MATH_DISPLAY_BRACKET.sub(keep_math(True), source)
    source = _MATH_INLINE_PAREN.sub(keep_math(False), source)
    source = _MATH_INLINE_DOLLAR.sub(keep_math(False), source)
    source = _MERMAID_FENCE.sub(
        lambda match: _stash(stash, "MERMAID", match.group(1).rstrip()),
        source,
    )

    md = _markdown()
    if md is None:
        fragment = chat_format.markdown_to_html(source)
    else:
        try:
            fragment = md.render(source)
        except Exception as exc:
            log.warning("Markdown rendering failed: %s", exc)
            fragment = chat_format.markdown_to_html(source)
    fragment = re.sub(
        r"<p>\s*(@@MERMAID\d+@@)\s*</p>", r"\1", fragment
    )
    return _restore(fragment, stash)


# ---- Transcript HTML ------------------------------------------------------

def _time_label(timestamp):
    try:
        value = float(timestamp)
    except (TypeError, ValueError):
        return ""
    return time.strftime("%H:%M", time.localtime(value))


def _att_value(attachment, key):
    if isinstance(attachment, dict):
        return attachment.get(key)
    return getattr(attachment, key, None)


_KIND_LABELS = {
    "image": "IMG",
    "pdf": "PDF",
    "docx": "DOC",
    "xlsx": "XLS",
    "text": "TXT",
    "file": "FILE",
}


def attachment_chips_html(attachments):
    chips = []
    for attachment in attachments or []:
        name = str(_att_value(attachment, "name") or "attachment")
        kind = str(_att_value(attachment, "kind") or "file")
        thumbnail = _att_value(attachment, "thumbnail")
        error = _att_value(attachment, "error")
        label = _KIND_LABELS.get(kind, "FILE")
        if thumbnail:
            if isinstance(thumbnail, str):
                source = thumbnail
            else:
                encoded = base64.b64encode(bytes(thumbnail)).decode("ascii")
                source = f"data:image/png;base64,{encoded}"
            icon = (
                '<img class="chip-thumb" alt="" '
                f'src="{html.escape(source, quote=True)}">'
            )
        else:
            icon = f'<span class="chip-icon">{html.escape(label)}</span>'
        chip_class = "chip chip-error" if error else "chip"
        title = f' title="{html.escape(str(error))}"' if error else ""
        chips.append(
            f'<span class="{chip_class}"{title}>{icon}'
            f'<span class="chip-name">{html.escape(name)}</span></span>'
        )
    if not chips:
        return ""
    return '<div class="attachments">' + "".join(chips) + "</div>"


def _file_uri(path):
    try:
        return Path(str(path)).expanduser().resolve().as_uri()
    except Exception:
        return ""


def _image_card(path):
    uri = _file_uri(path)
    if not uri:
        return ""
    return (
        '<figure class="generated">'
        f'<img src="{html.escape(uri, quote=True)}" alt="Generated image">'
        '<figcaption>Generated locally — saved in your Himari folder</figcaption>'
        "</figure>"
    )


def _tool_card(content):
    body = html.escape(str(content or "")[:2000])
    succeeded, _ = classify_result(content)
    if not succeeded:
        return (
            '<details class="tool tool-failed"><summary>TOOL · FAILED</summary>'
            f"<pre>{body}</pre></details>"
        )
    return (
        '<details class="tool"><summary>TOOL</summary>'
        f"<pre>{body}</pre></details>"
    )


def _card(
    role,
    content,
    timestamp,
    assistant_name,
    streaming=False,
    attachments=None,
    image=None,
):
    if role == "user":
        who = "You"
    elif role == "error":
        who = "Error"
    elif role == "system":
        who = "System"
    else:
        who = str(assistant_name or "Himari")
    text = str(content or "")
    body = markdown_to_html(text)
    if image:
        body += _image_card(image)
    body += attachment_chips_html(attachments)
    if streaming:
        body += (
            '<span class="typing" aria-label="Himari is typing">'
            "<i></i><i></i><i></i></span>"
            '<span class="cursor">&#9615;</span>'
        )
    stamp = _time_label(timestamp)
    stamp_html = f'<span class="time"> · {stamp}</span>' if stamp else ""
    copy_attr = f' data-copy="{html.escape(text, quote=True)}"' if text else ""
    copy_button = (
        '<button class="copy-msg" type="button" title="Copy message">Copy</button>'
        if text
        else ""
    )
    if role == "assistant":
        who_html = (
            '<span class="who with-avatar">'
            '<span class="avatar-badge" role="presentation">ひ</span>'
            f"{html.escape(who)}</span>"
        )
    else:
        who_html = f'<span class="who">{html.escape(who)}</span>'
    return (
        f'<article class="msg {html.escape(role)}"{copy_attr}>'
        f'<div class="meta">{who_html}'
        f"{stamp_html}{copy_button}</div>"
        f'<div class="bubble">{body}</div>'
        "</article>"
    )


def welcome_html(name="Himari"):
    safe_name = html.escape(str(name or "Himari"))
    chips = (
        ("What is on my screen?", "What is on my screen? Read the visible text and explain what matters."),
        ("Open a fireplace video", "Open a fireplace video."),
        ("Draw a mind map of my project", "Draw a mind map of my project."),
        ("Summarize a page", "Summarize the page I have open."),
    )
    return (
        '<section class="welcome">'
        f'<h1>Hey, I\'m {safe_name}.</h1>'
        "<p>Ask me to open something, read your screen, search the web, "
        "draw a diagram, or just talk. I only use tools you allow.</p>"
        '<div class="welcome-chips">'
        + "".join(
            f'<button type="button" data-prompt="{html.escape(prompt, quote=True)}">'
            f"{html.escape(label)}</button>"
            for label, prompt in chips
        )
        + "</div>"
        '<p class="welcome-note">The first reply after launch can take a few '
        "seconds while the local model wakes up. Everything stays on this PC."
        "</p></section>"
    )


def render_message_html(message, show_tools=False, assistant_name="Himari"):
    """Render one message to a transcript card, or None when it is filtered out."""
    if not isinstance(message, dict):
        return None
    role = str(message.get("role") or "assistant")
    content = str(message.get("content") or "")
    if role == "tool":
        return _tool_card(content) if show_tools else None
    if role not in ("user", "assistant", "error", "system"):
        return None
    return _card(
        role,
        content,
        message.get("ts"),
        assistant_name,
        streaming=bool(message.get("streaming")),
        attachments=message.get("attachments"),
        image=message.get("image"),
    )


def render_messages_html(
    messages,
    show_tools=False,
    assistant_name="Himari",
    empty=True,
):
    blocks = []
    for message in messages or []:
        block = render_message_html(
            message,
            show_tools=show_tools,
            assistant_name=assistant_name,
        )
        if block is not None:
            blocks.append(block)
    if not blocks:
        return welcome_html(assistant_name) if empty else ""
    return "".join(blocks)


def build_render_payload(
    messages,
    *,
    show_tools=False,
    assistant_name="Himari",
    force_scroll=False,
    rendered_count=None,
    rendered_streaming=False,
):
    """Build the JS payload for a transcript refresh.

    While the last visible message streams, only that card is re-rendered so
    the page is not rebuilt on every token. Any other change falls back to a
    full render to keep the page consistent with the message list.
    """
    renderable = [
        message
        for message in messages or []
        if isinstance(message, dict)
        and message.get("role") in ("user", "assistant", "error", "system", "tool")
        and not (message.get("role") == "tool" and not show_tools)
    ]
    streaming = any(bool(message.get("streaming")) for message in renderable)
    incremental = (
        streaming
        and rendered_streaming
        and rendered_count == len(renderable)
        and bool(renderable)
        and bool(renderable[-1].get("streaming"))
    )
    if incremental:
        last = render_message_html(
            renderable[-1],
            show_tools=show_tools,
            assistant_name=assistant_name,
        )
        if last is not None:
            payload = {
                "last": last,
                "streaming": True,
                "forceScroll": bool(force_scroll),
            }
            return payload, len(renderable), streaming
    payload = {
        "html": render_messages_html(
            renderable,
            show_tools=show_tools,
            assistant_name=assistant_name,
        ),
        "streaming": streaming,
        "forceScroll": bool(force_scroll),
    }
    return payload, len(renderable), streaming


# ---- Page shell -----------------------------------------------------------

def _css(colors, font_size, theme_name="dark"):
    p = colors
    color_scheme = "light" if str(theme_name) == "light" else "dark"
    return f"""
:root {{
  color-scheme: {color_scheme};
  --surface: {p['surface']};
  --card: {p['card']};
  --card-alt: {p['card_alt']};
  --text: {p['text']};
  --muted: {p['muted']};
  --border: {p['border']};
  --border-bright: {p.get('border_bright', p['border'])};
  --accent: {p['accent']};
  --accent-strong: {p['accent_strong']};
  --accent-dim: {p['accent_dim']};
  --accent-2: {p.get('accent_2', p['accent_strong'])};
  --code-bg: {p['code_bg']};
  --success: {p['success']};
  --warning: {p['warning']};
}}
* {{ box-sizing: border-box; }}
html, body {{
  margin: 0; padding: 0; color: {p['text']};
  font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
  font-size: {int(font_size)}px; line-height: 1.55;
}}
html {{
  background: {p['surface']};
}}
body {{
  background:
    radial-gradient(1100px 520px at 12% -12%, rgba(183,156,245,.10), transparent 62%),
    radial-gradient(900px 480px at 102% -4%, rgba(255,126,189,.09), transparent 58%),
    linear-gradient(180deg, {p['surface']} 0%, {p['surface']} 100%);
  min-height: 100vh;
}}
body {{ padding: 18px 20px 30px 20px; }}
::selection {{ background: {p['accent']}; color: #1b1017; }}
#transcript {{ max-width: 880px; margin: 0 auto; display: flex;
               flex-direction: column; gap: 14px; }}
.msg {{ display: flex; flex-direction: column; }}
.msg.user {{ align-items: flex-end; }}
.msg.enter {{ animation: msg-in .34s cubic-bezier(.21,.75,.28,1) both; }}
.msg.no-enter {{ animation: none; }}
@keyframes msg-in {{
  from {{ opacity: 0; transform: translateY(12px) scale(.995); }}
  to {{ opacity: 1; transform: none; }}
}}
.meta {{ font-size: 10px; font-weight: 700; letter-spacing: .8px;
         text-transform: uppercase; color: {p['muted']};
         margin: 0 6px 5px 6px; display: flex; align-items: center; gap: 6px; }}
.meta .time {{ font-weight: 400; letter-spacing: 0; }}
.who.with-avatar {{ display: inline-flex; align-items: center; gap: 7px; }}
.avatar-badge {{
  width: 20px; height: 20px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  background: radial-gradient(circle at 32% 26%, {p['accent_strong']}, {p['accent_2']} 72%);
  color: #1b1017; font-size: 11px; font-weight: 800; letter-spacing: 0;
  box-shadow: 0 0 0 1px {p['accent_dim']}, 0 0 12px rgba(255,126,189,.32);
}}
.bubble {{ padding: 12px 16px; border-radius: 15px;
           background: linear-gradient(180deg, {p['card']}, {p['assistant_bubble']});
           border: 1px solid {p['border']}; max-width: 100%;
           overflow-wrap: anywhere;
           box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
           transition: border-color .18s ease, box-shadow .18s ease; }}
.msg:hover .bubble {{ border-color: {p['border_bright']};
                      box-shadow: 0 8px 26px rgba(0,0,0,.22); }}
.msg.user .bubble {{ background: linear-gradient(160deg, {p['user_bubble']}, {p['card_alt']});
                     border-color: {p['accent_dim']};
                     max-width: 78%; border-bottom-right-radius: 5px; }}
.msg.assistant .bubble {{ border-left: 3px solid {p['accent']};
                          border-bottom-left-radius: 5px; }}
.msg.error .bubble {{ background: {p['error_bubble']}; border-color: {p['error']};
                      color: {p['error']}; }}
.msg.system .bubble {{ background: {p['system_bubble']}; color: {p['muted']};
                       font-size: .92em; border-style: dashed; }}

.bubble > :first-child {{ margin-top: 0; }}
.bubble > :last-child {{ margin-bottom: 0; }}
.bubble p {{ margin: 0 0 9px 0; }}
.bubble h1, .bubble h2, .bubble h3, .bubble h4 {{
  margin: 14px 0 8px 0; line-height: 1.3; color: {p['accent_strong']};
}}
.bubble h1 {{ font-size: 1.32em; }}
.bubble h2 {{ font-size: 1.18em; }}
.bubble h3 {{ font-size: 1.06em; }}
.bubble ul, .bubble ol {{ margin: 6px 0 10px 0; padding-left: 24px; }}
.bubble li {{ margin: 3px 0; }}
.bubble li > p {{ margin: 0; }}
.bubble blockquote {{ margin: 8px 0; padding: 4px 12px;
  border-left: 3px solid {p['accent_dim']}; color: {p['muted']}; }}
.bubble a {{ color: {p['accent']}; text-decoration: underline; }}
.bubble hr {{ border: none; border-top: 1px solid {p['border']}; margin: 14px 0; }}
.bubble strong {{ color: {p['text']}; }}
.bubble code {{ font-family: "Cascadia Mono", Consolas, monospace; font-size: .9em;
  background: {p['code_bg']}; border: 1px solid {p['border']};
  border-radius: 5px; padding: 1px 5px; }}
.bubble pre {{ background: {p['code_bg']}; border: 1px solid {p['border']};
  border-radius: 9px; padding: 10px 12px; overflow: auto; margin: 10px 0; }}
.bubble pre code {{ background: none; border: none; padding: 0; }}
.code-block {{ background: {p['code_bg']}; border: 1px solid {p['border']};
  border-radius: 9px; margin: 10px 0; overflow: hidden; }}
.code-block pre {{ background: none; border: none; border-radius: 0;
  margin: 0; padding: 10px 12px; }}
.code-bar {{ display: flex; align-items: center; justify-content: space-between;
  padding: 3px 6px 3px 12px; border-bottom: 1px solid {p['border']};
  background: {p['card']}; }}
.code-lang {{ color: {p['muted']}; font-size: .68em; font-weight: 700;
  letter-spacing: .8px; text-transform: uppercase; }}
.copy-code, .copy-msg {{ font: inherit; background: transparent;
  color: {p['muted']}; border: 1px solid transparent; border-radius: 5px;
  padding: 1px 7px; cursor: pointer; opacity: 0;
  transition: opacity .12s ease, color .12s ease; }}
.copy-msg {{ margin-left: auto; font-size: 9px; font-weight: 600;
  letter-spacing: .5px; text-transform: uppercase; }}
.code-block:hover .copy-code, .msg:hover .copy-msg,
.copy-code:focus, .copy-msg:focus {{ opacity: 1; }}
.copy-code:hover, .copy-msg:hover {{ color: {p['accent_strong']};
  border-color: {p['border']}; }}
.copy-failed {{ color: {p['warning']} !important; }}
.tok-com {{ color: {p['muted']}; font-style: italic; }}
.tok-str {{ color: {p['success']}; }}
.tok-kw {{ color: {p['accent_strong']}; }}
.tok-num {{ color: {p['warning']}; }}
.tok-fn {{ color: {p['accent']}; }}
.tok-var {{ color: {p['warning']}; }}
.bubble table {{ border-collapse: collapse; margin: 10px 0; width: 100%;
  font-size: .95em; }}
.bubble th, .bubble td {{ border: 1px solid {p['border']}; padding: 6px 10px;
  text-align: left; vertical-align: top; }}
.bubble th {{ background: {p['card_alt']}; color: {p['accent_strong']};
  font-weight: 600; }}
.bubble tbody tr:nth-child(even) td {{ background: {p['card']}; }}

.math {{ font-size: 1.02em; }}
.math-display, .math[data-display="1"] {{ display: block; text-align: center;
  overflow-x: auto; overflow-y: hidden; margin: 10px 0; }}
.math-error {{ color: {p['warning']}; font-family: Consolas, monospace; }}
.katex-display {{ margin: 10px 0; overflow-x: auto; overflow-y: hidden; }}
.katex {{ color: {p['text']}; }}
.mermaid-wrap {{ background: {p['code_bg']}; border: 1px solid {p['border']};
  border-radius: 10px; padding: 12px; margin: 10px 0; overflow: auto; }}
pre.mermaid {{ margin: 0; background: none; border: none; padding: 0;
  text-align: center; font-family: inherit; white-space: pre-wrap; }}
pre.mermaid svg {{ max-width: 100%; height: auto; }}
pre.mermaid.mermaid-error {{ text-align: left; color: {p['warning']};
  font-family: "Cascadia Mono", Consolas, monospace; font-size: .86em; }}

.attachments {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
.chip {{ display: inline-flex; align-items: center; gap: 7px;
  background: {p['card']}; border: 1px solid {p['border']};
  border-radius: 9px; padding: 4px 9px 4px 5px; font-size: .78em;
  color: {p['muted']}; }}
.chip-error {{ border-color: {p['warning']}; color: {p['warning']}; }}
.chip-icon {{ background: {p['card_alt']}; color: {p['accent']};
  border-radius: 5px; padding: 2px 6px; font-size: .82em; font-weight: 700; }}
.chip-thumb {{ width: 30px; height: 30px; object-fit: cover; border-radius: 6px;
  border: 1px solid {p['border']}; }}
.chip-name {{ max-width: 210px; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }}
.generated {{ margin: 10px 0 2px 0; }}
.generated img {{ max-width: min(520px, 100%); border-radius: 12px;
  border: 1px solid {p['border']}; display: block; }}
.generated figcaption {{ font-size: .78em; color: {p['muted']}; margin-top: 5px; }}
.img-alt {{ color: {p['muted']}; font-style: italic; }}
.cursor {{ color: {p['accent']}; animation: blink 1s steps(2, start) infinite; }}
@keyframes blink {{ to {{ visibility: hidden; }} }}
.typing {{ display: inline-flex; align-items: center; gap: 4px;
  margin-left: 8px; vertical-align: middle; }}
.typing i {{ width: 6px; height: 6px; border-radius: 50%;
  background: {p['accent']}; opacity: .45;
  animation: typing-dot 1.15s infinite ease-in-out; }}
.typing i:nth-child(2) {{ animation-delay: .16s; }}
.typing i:nth-child(3) {{ animation-delay: .32s; }}
@keyframes typing-dot {{
  0%, 78%, 100% {{ transform: translateY(0); opacity: .4; }}
  35% {{ transform: translateY(-4px); opacity: 1; }}
}}

details.tool {{ background: {p['tool_bubble']}; border: 1px solid {p['border']};
  border-radius: 9px; padding: 6px 10px; font-size: .82em;
  color: {p['muted']}; }}
details.tool summary {{ cursor: pointer; font-size: .78em; font-weight: 700;
  letter-spacing: .8px; }}
details.tool-failed {{ border-color: {p['warning']}; }}
details.tool-failed summary {{ color: {p['warning']}; }}
details.tool pre {{ margin: 6px 0 0 0; white-space: pre-wrap;
  font-family: "Cascadia Mono", Consolas, monospace; background: none;
  border: none; padding: 0; color: {p['muted']}; }}

.welcome {{ margin: 60px auto 0 auto; max-width: 620px; text-align: left;
  animation: welcome-in .5s cubic-bezier(.21,.75,.28,1) both; }}
@keyframes welcome-in {{
  from {{ opacity: 0; transform: translateY(16px); }}
  to {{ opacity: 1; transform: none; }}
}}
.welcome h1 {{ font-size: 1.7em; margin: 0 0 10px 0; color: {p['accent_strong']}; }}
.welcome p {{ color: {p['text']}; margin: 0 0 16px 0; }}
.welcome p.welcome-note {{ color: {p['muted']}; font-size: .82em; margin-top: 4px; }}
.welcome-chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.welcome-chips button, .welcome-chips span {{
  font: inherit; background: {p['card']}; border: 1px solid {p['border']};
  border-radius: 999px; padding: 6px 12px; font-size: .84em; color: {p['muted']};
  cursor: pointer; transition: border-color .16s ease, color .16s ease,
  background-color .16s ease, transform .16s ease; }}
.welcome-chips button:hover {{
  border-color: {p['accent']}; color: {p['text']};
  background: {p['card_alt']}; transform: translateY(-1px); }}
.welcome-chips button:active {{ transform: translateY(0); }}
@media (prefers-reduced-motion: reduce) {{
  .msg.enter, .welcome, .typing i, .cursor {{ animation: none; }}
  .welcome-chips button, .bubble {{ transition: none; }}
}}

::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: {p['border']}; border-radius: 5px; }}
::-webkit-scrollbar-thumb:hover {{ background: {p['accent_dim']}; }}
"""


def shell_html(colors=None, font_size=14, theme_name="dark"):
    p = colors or theme_palette(theme_name)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data: file:; font-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none';">
<link rel="stylesheet" href="katex/katex.min.css">
<style>{_css(p, font_size, theme_name)}</style>
<script src="katex/katex.min.js" defer></script>
<script src="mermaid.min.js" defer></script>
<script src="himari-chat.js" defer></script>
</head>
<body data-theme="{html.escape(str(theme_name))}">
<div id="transcript"></div>
</body></html>"""


# ---- Views ----------------------------------------------------------------

class ClassicChatView(QTextBrowser):
    """Plain QTextBrowser transcript used when QtWebEngine is unavailable."""

    def __init__(self, parent=None, colors=None, font_size=14):
        super().__init__(parent)
        self._colors = colors or theme_palette("dark")
        self.setObjectName("ChatView")
        self.setOpenExternalLinks(True)
        self.setFont(QFont("Segoe UI", int(font_size)))

    def render_messages(
        self,
        messages,
        show_tools=False,
        assistant_name="Himari",
        colors=None,
        force_scroll=False,
    ):
        scroll = self.verticalScrollBar()
        at_bottom = scroll.value() >= scroll.maximum() - 30
        streaming = any(
            isinstance(message, dict) and message.get("streaming")
            for message in messages or []
        )
        self.setHtml(
            chat_format.render_messages_html(
                messages,
                show_tools=show_tools,
                assistant_name=assistant_name,
                colors=colors or self._colors,
            )
        )
        if force_scroll or at_bottom or streaming:
            scroll.setValue(scroll.maximum())

    def selected_text(self, callback):
        text = self.textCursor().selectedText().replace("\u2029", "\n").strip()
        callback(text)

    def scroll_to_bottom(self):
        scroll = self.verticalScrollBar()
        scroll.setValue(scroll.maximum())


try:
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEB_ENGINE_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on the Qt build
    QWebEnginePage = None
    QWebEngineProfile = None
    QWebEngineSettings = None
    QWebEngineView = None
    WEB_ENGINE_AVAILABLE = False
    log.warning("QtWebEngine is unavailable; using the classic chat view: %s", exc)


if WEB_ENGINE_AVAILABLE:

    class _ChatPage(QWebEnginePage):
        copyRequested = Signal(str)
        fillRequested = Signal(str)

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            scheme = url.scheme().lower()
            link_clicked = (
                nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
            )
            if link_clicked or scheme in ("http", "https"):
                QDesktopServices.openUrl(url)
                return False
            return scheme in ("about", "file", "data", "")

        def javaScriptPrompt(self, securityOrigin, msg, defaultValue):
            if msg == "himari-copy":
                self.copyRequested.emit(str(defaultValue or ""))
                return (True, "1")
            if msg == "himari-fill":
                self.fillRequested.emit(str(defaultValue or ""))
                return (True, "1")
            return (False, "")

    class ChatWebView(QWebEngineView):
        """Transcript view backed by a local, script-locked web page."""

        fillRequested = Signal(str)

        def __init__(
            self,
            parent=None,
            colors=None,
            assistant_name="Himari",
            font_size=14,
            theme_name="dark",
        ):
            super().__init__(parent)
            self._colors = colors or theme_palette(theme_name)
            self._font_size = int(font_size)
            self._theme_name = str(theme_name)
            self._ready = False
            self._pending = None
            self._rendered_count = None
            self._rendered_streaming = False
            self.setObjectName("ChatView")
            self._profile = QWebEngineProfile(self)
            self._page = _ChatPage(self._profile, self)
            self.setPage(self._page)
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
            settings = self.settings()
            for attribute, enabled in (
                (
                    QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
                    True,
                ),
                (
                    QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                    False,
                ),
                (QWebEngineSettings.WebAttribute.JavascriptEnabled, True),
                (QWebEngineSettings.WebAttribute.PluginsEnabled, False),
                (QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False),
                (QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, False),
                (QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True),
            ):
                try:
                    settings.setAttribute(attribute, enabled)
                except Exception:  # pragma: no cover - attribute exists in Qt 6
                    pass
            self.page().setBackgroundColor(QColor(self._colors["surface"]))
            self._page.copyRequested.connect(self._copy_requested)
            self._page.fillRequested.connect(self.fillRequested)
            self.loadFinished.connect(self._on_loaded)
            base = QUrl.fromLocalFile(str(ASSETS_DIR) + "/")
            self.setHtml(
                shell_html(self._colors, self._font_size, self._theme_name),
                base,
            )

        def _copy_requested(self, text):
            QApplication.clipboard().setText(str(text))

        def _on_loaded(self, ok):
            self._ready = bool(ok)
            if not ok:
                log.warning("The rich chat page failed to load")
                return
            if self._pending is not None:
                payload, self._pending = self._pending, None
                self._apply(payload)
            self.page().runJavaScript(
                "window.himari && window.himari.enableBridge();"
            )

        def render_messages(
            self,
            messages,
            show_tools=False,
            assistant_name="Himari",
            colors=None,
            force_scroll=False,
        ):
            payload, self._rendered_count, self._rendered_streaming = build_render_payload(
                messages,
                show_tools=show_tools,
                assistant_name=assistant_name,
                force_scroll=force_scroll,
                rendered_count=self._rendered_count,
                rendered_streaming=self._rendered_streaming,
            )
            if self._ready:
                self._apply(payload)
            else:
                self._pending = payload

        def _apply(self, payload):
            script = (
                "window.himari && window.himari.setContent("
                + json.dumps(payload, ensure_ascii=True)
                + ");"
            )
            self.page().runJavaScript(script)

        def selected_text(self, callback):
            script = (
                "window.himari ? window.himari.selection() : "
                "(window.getSelection ? String(window.getSelection()) : '');"
            )
            self.page().runJavaScript(script, callback)

        def scroll_to_bottom(self):
            self.page().runJavaScript(
                "window.himari && window.himari.scrollToBottom();"
            )


def create_chat_view(
    parent=None,
    colors=None,
    assistant_name="Himari",
    font_size=14,
    theme_name="dark",
    engine="web",
):
    colors = colors or theme_palette(theme_name)
    if engine != "classic" and WEB_ENGINE_AVAILABLE:
        try:
            return ChatWebView(
                parent,
                colors=colors,
                assistant_name=assistant_name,
                font_size=font_size,
                theme_name=theme_name,
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            log.warning("Rich chat view failed to start: %s", exc)
    return ClassicChatView(parent, colors=colors, font_size=font_size)
