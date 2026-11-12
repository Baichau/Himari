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

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import QTextBrowser

from . import chat_format
from .theme import palette as theme_palette

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
    body = markdown_to_html(content)
    if image:
        body += _image_card(image)
    body += attachment_chips_html(attachments)
    if streaming:
        body += '<span class="cursor">&#9615;</span>'
    stamp = _time_label(timestamp)
    stamp_html = f'<span class="time"> · {stamp}</span>' if stamp else ""
    return (
        f'<article class="msg {html.escape(role)}">'
        f'<div class="meta"><span class="who">{html.escape(who)}</span>'
        f"{stamp_html}</div>"
        f'<div class="bubble">{body}</div>'
        "</article>"
    )


def welcome_html(name="Himari"):
    safe_name = html.escape(str(name or "Himari"))
    chips = (
        "“Read what is on my screen”",
        "“Draw a mind map of my project”",
        "“Generate a picture of a rainy Tokyo street”",
    )
    return (
        '<section class="welcome">'
        f'<h1>Hey, I\'m {safe_name}.</h1>'
        "<p>Ask me to open something, read your screen, search the web, "
        "draw a diagram, or just talk. I only use tools you allow.</p>"
        '<div class="welcome-chips">'
        + "".join(f"<span>{chip}</span>" for chip in chips)
        + "</div></section>"
    )


def render_messages_html(
    messages,
    show_tools=False,
    assistant_name="Himari",
    empty=True,
):
    blocks = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "assistant")
        content = str(message.get("content") or "")
        if role == "tool":
            if show_tools:
                blocks.append(_tool_card(content))
            continue
        if role not in ("user", "assistant", "error", "system"):
            continue
        blocks.append(
            _card(
                role,
                content,
                message.get("ts"),
                assistant_name,
                streaming=bool(message.get("streaming")),
                attachments=message.get("attachments"),
                image=message.get("image"),
            )
        )
    if not blocks:
        return welcome_html(assistant_name) if empty else ""
    return "".join(blocks)


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
  --accent: {p['accent']};
  --accent-strong: {p['accent_strong']};
  --accent-dim: {p['accent_dim']};
  --code-bg: {p['code_bg']};
}}
* {{ box-sizing: border-box; }}
html, body {{
  margin: 0; padding: 0; background: {p['surface']}; color: {p['text']};
  font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
  font-size: {int(font_size)}px; line-height: 1.55;
}}
body {{ padding: 18px 20px 30px 20px; }}
::selection {{ background: {p['accent']}; color: #1b1017; }}
#transcript {{ max-width: 880px; margin: 0 auto; display: flex;
               flex-direction: column; gap: 14px; }}
.msg {{ display: flex; flex-direction: column; }}
.msg.user {{ align-items: flex-end; }}
.meta {{ font-size: 10px; font-weight: 700; letter-spacing: .8px;
         text-transform: uppercase; color: {p['muted']};
         margin: 0 6px 4px 6px; }}
.meta .time {{ font-weight: 400; letter-spacing: 0; }}
.bubble {{ padding: 12px 16px; border-radius: 14px; background: {p['assistant_bubble']};
           border: 1px solid {p['border']}; max-width: 100%;
           overflow-wrap: anywhere; }}
.msg.user .bubble {{ background: {p['user_bubble']}; border-color: {p['accent_dim']};
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

details.tool {{ background: {p['tool_bubble']}; border: 1px solid {p['border']};
  border-radius: 9px; padding: 6px 10px; font-size: .82em;
  color: {p['muted']}; }}
details.tool summary {{ cursor: pointer; font-size: .78em; font-weight: 700;
  letter-spacing: .8px; }}
details.tool pre {{ margin: 6px 0 0 0; white-space: pre-wrap;
  font-family: "Cascadia Mono", Consolas, monospace; background: none;
  border: none; padding: 0; color: {p['muted']}; }}

.welcome {{ margin: 60px auto 0 auto; max-width: 620px; text-align: left; }}
.welcome h1 {{ font-size: 1.7em; margin: 0 0 10px 0; color: {p['accent_strong']}; }}
.welcome p {{ color: {p['text']}; margin: 0 0 16px 0; }}
.welcome-chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.welcome-chips span {{ background: {p['card']}; border: 1px solid {p['border']};
  border-radius: 999px; padding: 6px 12px; font-size: .84em; color: {p['muted']}; }}

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
        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            scheme = url.scheme().lower()
            link_clicked = (
                nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
            )
            if link_clicked or scheme in ("http", "https"):
                QDesktopServices.openUrl(url)
                return False
            return scheme in ("about", "file", "data", "")

    class ChatWebView(QWebEngineView):
        """Transcript view backed by a local, script-locked web page."""

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
            self.loadFinished.connect(self._on_loaded)
            base = QUrl.fromLocalFile(str(ASSETS_DIR) + "/")
            self.setHtml(
                shell_html(self._colors, self._font_size, self._theme_name),
                base,
            )

        def _on_loaded(self, ok):
            self._ready = bool(ok)
            if not ok:
                log.warning("The rich chat page failed to load")
                return
            if self._pending is not None:
                payload, self._pending = self._pending, None
                self._apply(payload)

        def render_messages(
            self,
            messages,
            show_tools=False,
            assistant_name="Himari",
            colors=None,
            force_scroll=False,
        ):
            streaming = any(
                isinstance(message, dict) and message.get("streaming")
                for message in messages or []
            )
            payload = {
                "html": render_messages_html(
                    messages,
                    show_tools=show_tools,
                    assistant_name=assistant_name,
                ),
                "streaming": streaming,
                "forceScroll": bool(force_scroll),
            }
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
