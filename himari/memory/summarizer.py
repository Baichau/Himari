"""Conversation summaries generated only through the local Ollama endpoint."""

import logging

from .. import db
from ..config import load as load_config

log = logging.getLogger("himari.memory")

SUMMARY_PROMPT = (
    "Summarize the following conversation in 3-5 short factual sentences. "
    "Only include information stated by the user. Do not invent details.\n\n"
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
    transcript = "\n".join(
        f"{message['role']}: {message['content']}" for message in history
    )
    chat = chat or _default_chat
    try:
        summary = chat([{"role": "user", "content": SUMMARY_PROMPT + transcript}])
    except Exception as exc:
        log.warning("Local conversation summarization failed: %s", exc)
        return None
    summary = (summary or "").strip()
    if not summary:
        return None
    if save:
        db.save_summary(session, summary)
    return summary