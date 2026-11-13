"""Conservative contradiction hints for saved memories.

This is a lexical heuristic, not a semantic prover: it flags pairs whose
content largely overlaps but whose polarity differs (negation or an antonym).
"""

import re

_NEGATIONS = {
    "not",
    "never",
    "none",
    "nothing",
    "cannot",
    "without",
    "hate",
    "hates",
    "dislike",
    "dislikes",
    "avoid",
    "avoids",
    "stopped",
    "quit",
    "disabled",
}

_ANTONYMS = (
    ("like", "dislike"),
    ("likes", "dislikes"),
    ("love", "hate"),
    ("loves", "hates"),
    ("always", "never"),
    ("prefer", "avoid"),
    ("prefers", "avoids"),
    ("enable", "disable"),
    ("enabled", "disabled"),
)

_OVERLAP_THRESHOLD = 0.5


def _tokens(text):
    return {
        token
        for token in re.findall(r"[^\W_]+", str(text or "").casefold())
        if len(token) > 2
    }


def _overlap(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _antonym(left, right):
    for first, second in _ANTONYMS:
        if (first in left and second in right) or (second in left and first in right):
            return f"'{first}' vs '{second}'"
    return ""


def _text_and_id(memory):
    if isinstance(memory, dict):
        return memory.get("text"), memory.get("id")
    return getattr(memory, "text", None), getattr(memory, "id", None)


def find_conflicts(memories):
    """Return ``{first, second, first_id, second_id, reason}`` hints."""
    items = []
    for memory in memories or []:
        text, identifier = _text_and_id(memory)
        if isinstance(text, str) and text.strip():
            items.append(
                {
                    "id": identifier,
                    "text": text.strip(),
                    "tokens": _tokens(text),
                }
            )

    conflicts = []
    for index, left in enumerate(items):
        for right in items[index + 1:]:
            if _overlap(left["tokens"], right["tokens"]) < _OVERLAP_THRESHOLD:
                continue
            antonym = _antonym(left["tokens"], right["tokens"])
            negated = bool(left["tokens"] & _NEGATIONS) != bool(
                right["tokens"] & _NEGATIONS
            )
            if not antonym and not negated:
                continue
            conflicts.append(
                {
                    "first": left["text"],
                    "second": right["text"],
                    "first_id": left["id"],
                    "second_id": right["id"],
                    "reason": antonym or "one memory is negated",
                }
            )
    return conflicts
