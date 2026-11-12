"""Safe HTML rendering for the chat transcript.

The converter supports the useful subset of Markdown a local chat model emits
without pulling in an extra dependency. All model text is HTML-escaped first;
only http(s) links become anchors.
"""

import html
import re
import time

from .theme import palette as theme_palette

_FENCE = re.compile(r"```([A-Za-z0-9_+.\-]*)[ \t]*\n(.*?)(?:```|$)", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BARE_URL = re.compile(r"(?<![\"'=])(https?://[^\s<]+)")
_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_STRIKE = re.compile(r"~~([^~\n]+)~~")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_HEADING = re.compile(r"^\s*(#{1,3})\s+(.*)$")


def _link(url, label, color):
    safe_url = html.escape(url, quote=True)
    return (
        f'<a href="{safe_url}" style="color:{color}; text-decoration:underline;">'
        f"{label}</a>"
    )


def markdown_to_html(text, colors=None):
    p = colors or theme_palette("dark")
    source = str(text or "")
    code_blocks = []

    def stash_code(match):
        language = (match.group(1) or "").strip()
        body = html.escape(match.group(2).rstrip("\n"))
        label = (
            f'<div style="color:{p["muted"]}; font-size:10px; margin-bottom:4px;">'
            f"{html.escape(language.upper())}</div>"
            if language
            else ""
        )
        code_blocks.append(
            f'<table width="100%" cellspacing="0" cellpadding="8" '
            f'bgcolor="{p["code_bg"]}"><tr><td>{label}'
            f'<span style="font-family:Consolas,monospace; font-size:12px; '
            f'color:{p["text"]};">{body.replace(chr(10), "<br>")}</span>'
            f"</td></tr></table>"
        )
        return f"\x00F{len(code_blocks) - 1}\x00"

    source = _FENCE.sub(stash_code, source)
    escaped = html.escape(source)
    lines = []
    for raw_line in escaped.split("\n"):
        stripped = raw_line.strip()
        heading = _HEADING.match(raw_line)
        bullet = _BULLET.match(raw_line)
        if heading:
            level = len(heading.group(1))
            size = {1: 17, 2: 15, 3: 13}.get(level, 13)
            lines.append(
                f'<b style="font-size:{size}px; color:{p["text"]};">'
                f"{heading.group(2)}</b>"
            )
        elif bullet:
            lines.append(f"• {bullet.group(1)}")
        elif stripped.startswith("&gt; "):
            lines.append(
                f'<span style="color:{p["muted"]};">▎ {raw_line.strip()[5:]}</span>'
            )
        else:
            lines.append(raw_line)
    body = "<br>".join(lines)

    inline_codes = []

    def stash_inline(match):
        inline_codes.append(match.group(1))
        return f"\x00C{len(inline_codes) - 1}\x00"

    body = _INLINE_CODE.sub(stash_inline, body)

    links = []

    def stash_link(match):
        label = match.group(1)
        url = match.group(2)
        links.append(_link(url, label, p["accent"]))
        return f"\x00L{len(links) - 1}\x00"

    body = _MD_LINK.sub(stash_link, body)

    def stash_bare(match):
        url = match.group(1)
        trailing = ""
        while url and url[-1] in ".,;:!?":
            trailing = url[-1] + trailing
            url = url[:-1]
        links.append(_link(url, html.escape(url), p["accent"]))
        return f"\x00L{len(links) - 1}\x00{trailing}"

    body = _BARE_URL.sub(stash_bare, body)
    body = _BOLD.sub(r"<b>\1</b>", body)
    body = _STRIKE.sub(r"<s>\1</s>", body)
    body = _ITALIC.sub(r"<i>\1</i>", body)

    for index, code in enumerate(inline_codes):
        body = body.replace(
            f"\x00C{index}\x00",
            f'<span style="font-family:Consolas,monospace; background-color:'
            f'{p["code_bg"]}; color:{p["text"]}; padding:1px 4px;">'
            f"{code}</span>",
        )
    for index, anchor in enumerate(links):
        body = body.replace(f"\x00L{index}\x00", anchor)
    for index, block in enumerate(code_blocks):
        body = body.replace(f"\x00F{index}\x00", block)
    return body


def _time_label(timestamp):
    try:
        value = float(timestamp)
    except (TypeError, ValueError):
        return ""
    return time.strftime("%H:%M", time.localtime(value))


def welcome_html(name="Himari", colors=None):
    p = colors or theme_palette("dark")
    safe_name = html.escape(str(name or "Himari"))
    return (
        f'<div style="margin:36px 24px; color:{p["muted"]};">'
        f'<div style="font-size:22px; font-weight:700; color:{p["accent_strong"]};">'
        f"Hey, I'm {safe_name}.</div>"
        f'<div style="font-size:13px; margin-top:10px; color:{p["text"]};">'
        "Ask me to open something, read your screen, search the web, "
        "or just talk. I only use tools you allow.</div>"
        f'<div style="font-size:12px; margin-top:14px; color:{p["muted"]};">'
        "Try: “What is my active window?” &nbsp;·&nbsp; “Open Spotify” "
        "&nbsp;·&nbsp; “Read what is on my screen”</div>"
        "</div>"
    )


def _attachment_name(item):
    value = (
        item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
    )
    return str(value or "attachment")


def _card(
    role,
    content,
    timestamp,
    colors,
    assistant_name,
    streaming=False,
    attachments=None,
    image=None,
):
    p = colors
    if role == "user":
        label, sender_color, background = "You", p["muted"], p["user_bubble"]
        indent_left, indent_right = "16%", "0%"
    elif role == "error":
        label, sender_color, background = "Error", p["error"], p["error_bubble"]
        indent_left, indent_right = "0%", "16%"
    elif role == "system":
        label, sender_color, background = "System", p["muted"], p["system_bubble"]
        indent_left, indent_right = "8%", "8%"
    else:
        label = str(assistant_name or "Himari")
        sender_color, background = p["accent"], p["assistant_bubble"]
        indent_left, indent_right = "0%", "16%"
    body = markdown_to_html(content, p)
    attachments = [item for item in (attachments or []) if item is not None]
    if attachments:
        names = " · ".join(html.escape(_attachment_name(item)) for item in attachments)
        body += (
            f'<div style="font-size:10px; color:{p["muted"]}; margin-top:6px;">'
            f"Attached: {names}</div>"
        )
    if image:
        body += (
            f'<div style="font-size:11px; color:{p["muted"]}; margin-top:6px;">'
            f"Generated image saved to {html.escape(str(image))}</div>"
        )
    if streaming:
        body += f'<span style="color:{p["accent"]};">▍</span>'
    if role == "system":
        body = f'<span style="font-size:12px; color:{p["muted"]};">{body}</span>'
    stamp = _time_label(timestamp)
    meta = (
        f'<span style="font-size:10px; font-weight:700; color:{sender_color};">'
        f"{html.escape(label.upper())}</span>"
        f'<span style="font-size:10px; color:{p["muted"]};"> · {stamp}</span>'
    )
    card = (
        f'<table width="100%" cellspacing="0" cellpadding="10" bgcolor="{background}">'
        f'<tr><td>{meta}<div style="font-size:13px; color:{p["text"]}; '
        f'margin-top:4px;">{body}</div></td></tr></table>'
    )
    return (
        f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
        f'<td width="{indent_left}"></td><td>{card}</td>'
        f'<td width="{indent_right}"></td></tr></table>'
        f'<div style="font-size:5px;"> </div>'
    )


def _tool_card(content, colors):
    p = colors
    body = html.escape(str(content or "")[:900])
    return (
        f'<table width="100%" cellspacing="0" cellpadding="7" bgcolor="{p["tool_bubble"]}">'
        f'<tr><td><span style="font-size:9px; font-weight:700; color:{p["muted"]};">'
        f"TOOL</span><br>"
        f'<span style="font-family:Consolas,monospace; font-size:11px; '
        f'color:{p["muted"]};">{body}</span></td></tr></table>'
        f'<div style="font-size:5px;"> </div>'
    )


def render_messages_html(
    messages,
    show_tools=False,
    assistant_name="Himari",
    colors=None,
    empty=True,
):
    p = colors or theme_palette("dark")
    blocks = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "assistant")
        content = str(message.get("content") or "")
        if role == "tool":
            if show_tools:
                blocks.append(_tool_card(content, p))
            continue
        if role not in ("user", "assistant", "error", "system"):
            continue
        blocks.append(
            _card(
                role,
                content,
                message.get("ts"),
                p,
                assistant_name,
                streaming=bool(message.get("streaming")),
                attachments=message.get("attachments"),
                image=message.get("image"),
            )
        )
    if not blocks:
        if not empty:
            return ""
        return welcome_html(assistant_name, p)
    return (
        f'<div style="background-color:{p["surface"]}; color:{p["text"]};">'
        + "".join(blocks)
        + "</div>"
    )
