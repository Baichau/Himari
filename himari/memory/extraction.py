"""Extract memory candidates from explicit user requests only."""

import re

from ..db import _SENSITIVE_MEMORY, _TEMPORARY_MEMORY

_REQUEST = re.compile(
    r"^\s*(?:please\s+)?remember\s+that\s+(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CATEGORY_HINTS = (
    ("preferences", re.compile(r"\b(prefer|like|love|favorite|favourite|hate|dislike)\b", re.IGNORECASE)),
    ("projects", re.compile(r"\b(project|working on|building|developing|repository)\b", re.IGNORECASE)),
    ("decisions", re.compile(r"\b(decided|choose|chose|settled on|picked)\b", re.IGNORECASE)),
    ("workflows", re.compile(r"\b(workflow|always|every time|routine|process)\b", re.IGNORECASE)),
)


def extract_candidate(message):
    """Return {'text', 'category'} for an explicit 'remember that ...' request."""
    if not isinstance(message, str):
        return None
    match = _REQUEST.match(message)
    if not match:
        return None
    text = match.group(1).strip()
    if not text or len(text) > 240:
        return None
    if _SENSITIVE_MEMORY.search(text) or _TEMPORARY_MEMORY.search(text):
        return None
    category = "personal_context"
    for name, pattern in _CATEGORY_HINTS:
        if pattern.search(text):
            category = name
            break
    return {"text": text, "category": category}