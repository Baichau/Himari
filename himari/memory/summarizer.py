"""Conversation summaries generated only through the local Ollama endpoint."""

import logging

from .. import db
from ..config import load as load_config

log = logging.getLogger("himari.memory")

SUMMARY_PROMPT = (
    "Write a compact memory of this conversation for the assistant to reuse later. "
    "Cover, in at most 180 words: who the user is here, what they asked for, "
    "decisions and preferences they stated, tasks that are done or still open, "
    "names, numbers, paths and links they mentioned, and promises the assistant "
    "made. Keep it factual and third-person; never invent details. "
    "Write short lines, one topic per line.\n\n"
)


def _default_chat(messages):
    import ollama

    config = load_config()
    settings = config["ollama"]
    client = ollama.Client(
        host=settings["host"],
        timeout=settings.get("timeout_seconds", 180),
    )
    response = client.chat(model=settings["chat_model"], messages=messages, think=False)
    return response.message.content


def summarize_session(session, chat=None, save=True, limit=40):
    """Summarize stored messages; returns None when there is nothing usable."""
    history = db.history(session, limit=limit)
    if len(history) < 2:
        return None
    return _summarize_lines(
        session,
        (f"{message['role']}: {message['content']}" for message in history),
        chat=chat,
        save=save,
    )


def summarize_older(session, keep_recent=32, chat=None, save=True, limit=500):
    """Summarize everything except the newest turns so long chats keep context."""
    rows = db.messages_detailed(session, limit=limit)
    older = rows[:-keep_recent] if keep_recent > 0 else rows
    older = list(reversed(older))
    if len(older) < 6:
        return None
    return _summarize_lines(
        session,
        (f"{message['role']}: {message['content']}" for message in older),
        chat=chat,
        save=save,
    )


def _summarize_lines(session, lines, chat=None, save=True):
    transcript = "\n".join(lines)
    if not transcript.strip():
        return None
    chat = chat or _default_chat
    try:
        summary = chat([
            {"role": "user", "content": SUMMARY_PROMPT + transcript[-24000:]}
        ])
    except Exception as exc:
        log.warning("Local conversation summarization failed: %s", exc)
        return None
    summary = (summary or "").strip()
    if not summary:
        return None
    if save:
        db.save_summary(session, summary)
    return summary