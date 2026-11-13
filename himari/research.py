"""Automatic web verification for factual questions."""

import re
import threading
import time

from . import db
from .config import load
from .tools import _notify_progress, research_web

_CACHE_TTL_SECONDS = 600
_MAX_QUERY_CHARS = 240

_SEARCH_REQUEST = re.compile(
    r"^(?:hey\s+himari[,\s]*)?(?:please\s+)?"
    r"(?:can|could|would|will)\s+you\s+"
    r"(?:search|look\s+up|research|find\s+out|google)\b",
    re.I,
)
_QUESTION_START = re.compile(
    r"^(?:hey\s+himari[,\s]*)?(?:please\s+)?(?:"
    r"who(?:'s| is| was| are)|what(?:'s| is| was| are)|"
    r"when(?:'s| is| was| were)|where(?:'s| is| was| are)|"
    r"why\b|how\b|which\b|whose\b|whom\b|"
    r"is\b|are\b|was\b|were\b|does\b|did\b|could\b|should\b|"
    r"tell\s+me\s+about|explain\b|search\b|look\s+up\b|research\b|find\s+out\b"
    r")",
    re.I,
)
_LOCAL_START = re.compile(
    r"^(?:hey\s+himari[,\s]*)?(?:please\s+)?(?:"
    r"hi\b|hello\b|hey\b|thanks\b|thank\s+you\b|good\s+(?:morning|night|evening)\b|"
    r"open\b|launch\b|close\b|play\b|pause\b|resume\b|stop\b|set\b|turn\b|"
    r"mute\b|unmute\b|volume\b|maximize\b|minimize\b|screenshot\b|capture\b|"
    r"read\b|show\b|hide\b|remember\b|forget\b|save\b|add\b|delete\b|clear\b|edit\b|"
    r"what\s+(?:can|do)\s+you\b|what\s+are\s+you\b|who\s+are\s+you\b|"
    r"what\s+(?:is|'s)\s+your\b|how\s+are\s+you\b|"
    r"are\s+you\b|can\s+you\b|will\s+you\b|would\s+you\b|"
    r"do\s+you\s+(?:remember|know\s+me|think|like|have|see|hear)\b|"
    r"who\s+am\s+i\b|where\s+am\s+i\b|what\s+time\b|what\s+date\b|what\s+day\b"
    r")",
    re.I,
)
_LOCAL_REFERENCE = re.compile(
    r"\b(?:my|our)\s+(?:name|memory|memories|screen|window|pc|computer|"
    r"files?|folders?|desktop|schedule|calendar|settings?)\b",
    re.I,
)
_LOCAL_STATE = re.compile(
    r"^(?:is|are|was|were)\b.*\b(?:open|running|active|connected|installed)\b",
    re.I,
)
_HOW_LOCAL = re.compile(
    r"\bhow\s+(?:do|can|should)\s+i\s+(?:open|launch|close|play|set|turn|"
    r"maximize|minimize|mute|screenshot|capture|change|find|get)\b",
    re.I,
)
_RESEARCH_HINT = re.compile(
    r"\b(?:latest|news|today|current|currently|release\s+date|"
    r"who(?:'s| is| was)|what(?:'s| is| was)|where(?:'s| is| was)|"
    r"when(?:'s| is| was)|tell\s+me\s+about|explain|compare|review|"
    r"price|weather|score|schedule|meaning|history|biography)\b",
    re.I,
)
_CLEAN_PREFIX = re.compile(
    r"^(?:hey\s+himari[,\s]*)?(?:please\s+)?(?:"
    r"(?:can|could|would|will)\s+you\s+(?:please\s+)?"
    r"(?:search(?:\s+the\s+web)?(?:\s+for)?|look\s+up|research|"
    r"find\s+out(?:\s+about)?|google)|"
    r"search(?:\s+the\s+web)?(?:\s+for)?|look\s+up|research|"
    r"find\s+out(?:\s+about)?|google|"
    r"tell\s+me\s+about|what\s+do\s+you\s+know\s+about|explain"
    r")\s+",
    re.I,
)

_cache = {}
_cache_lock = threading.Lock()


def _clean_query(text):
    query = re.sub(r"\s+", " ", str(text or "")).strip()
    query = _CLEAN_PREFIX.sub("", query, count=1)
    if "?" in query:
        query = query.split("?", 1)[0]
    query = query.strip(" .,!?:;\"'")
    if len(query) > _MAX_QUERY_CHARS:
        query = query[:_MAX_QUERY_CHARS].rsplit(" ", 1)[0].strip()
    return query


def should_research(text):
    """Return True when a question should be verified against public sources."""
    text = str(text or "").strip()
    if len(text) < 4 or len(text) > 300:
        return False
    if not any(char.isalpha() for char in text):
        return False
    if db.memory_is_sensitive(text):
        return False
    if _SEARCH_REQUEST.match(text):
        return True
    if _HOW_LOCAL.search(text):
        return False
    if _LOCAL_REFERENCE.search(text):
        return False
    if _LOCAL_STATE.match(text):
        return False
    if _LOCAL_START.match(text):
        return False
    return bool(_QUESTION_START.match(text) or _RESEARCH_HINT.search(text))


def research_for_prompt(text, *, cancel=None, progress=None):
    """Return web results for a factual question, or None when not needed."""
    if not should_research(text):
        return None
    try:
        if not load().get("permissions", {}).get("allow_web_research", True):
            return None
    except Exception:
        return None
    query = _clean_query(text)
    if not query:
        return None
    key = query.casefold()
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            _notify_progress(progress, "Using recently cached web results…")
            return cached[1]
    result = research_web(query, cancel=cancel, progress=progress)
    if isinstance(result, str) and "Source:" in result:
        with _cache_lock:
            if len(_cache) >= 64:
                _cache.clear()
            _cache[key] = (now, result)
    return result
