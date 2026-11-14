"""Prompt assembly for the persona.

The core safety and honesty prompt is always included; persona and mode only
add tone on top of it.
"""

from ..persona import SYSTEM as CORE_SYSTEM_PROMPT
from .persona import DEFAULT_PERSONA

TECHNICAL_ADDENDUM = (
    "This request is technical. Be precise and direct, state assumptions, and "
    "do not roleplay. Show commands or code only when useful, and say exactly "
    "what was not verified."
)

CONVERSATION_ADDENDUM = (
    "This is a casual conversation. Be cozy, warm, and natural, keep answers "
    "short, and let your personality show without performing or repeating "
    "catchphrases."
)


def is_technical_request(text):
    lowered = str(text or "").casefold()
    keywords = (
        "error", "traceback", "bug", "code", "python", "script", "command",
        "terminal", "install", "config", "function", "database", "sql",
        "git", "build", "test", "debug", "log", "api",
    )
    return any(keyword in lowered for keyword in keywords)


def build_system_prompt(persona=None, technical=False, extra=""):
    persona = persona or DEFAULT_PERSONA
    parts = [
        CORE_SYSTEM_PROMPT.strip(),
        persona.instruction_block(),
        TECHNICAL_ADDENDUM if technical else CONVERSATION_ADDENDUM,
    ]
    if extra:
        parts.append(str(extra).strip())
    return "\n\n".join(part for part in parts if part)


def build_messages(persona=None, messages=None, technical=False, extra=""):
    safe_messages = [
        dict(message)
        for message in (messages or [])
        if isinstance(message, dict) and message.get("role") != "system"
    ]
    return [
        {"role": "system", "content": build_system_prompt(persona, technical, extra)}
    ] + safe_messages
