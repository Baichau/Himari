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
_RECENCY = re.compile(
    r"\b(?:latest|news|today|tonight|currently|current|right now|"
    r"this\s+(?:week|month|year)|release\s+date|price|weather|forecast|"
    r"score|schedule|who\s+won|election|president|prime\s+minister|"
    r"chancellor|ceo|stock|market|patch\s+notes|just\s+(?:released|announced)|"
    r"20(?:2[5-9]|3\d))\b",
    re.I,
)
_VERIFY = re.compile(
    r"\b(?:is\s+it\s+true|fact[- ]?check|verify|double[- ]?check|"
    r"check\s+(?:if|whether)|source|cite)\b",
    re.I,
)
_DATE_TIME = re.compile(
    r"\b(?:what|which)\s+(?:day|date|time)\s+(?:is\s+it|is\s+today|today|now)\b"
    r"|\bwhat'?s\s+(?:the\s+)?(?:date|day|time)\s+(?:today|now)\b"
    r"|\btoday'?s\s+(?:date|day|day\s+of\s+the\s+week)\b"
    r"|\bwhat\s+day\s+is\s+(?:it|today)\b"
    r"|\bcurrent\s+(?:date|time|day)\b",
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
    if _DATE_TIME.search(text):
        return False
    if _HOW_LOCAL.search(text):
        return False
    if _LOCAL_REFERENCE.search(text):
        return False
    if _LOCAL_STATE.match(text):
        return False
    if _LOCAL_START.match(text):
        return False
    return bool(_RECENCY.search(text) or _VERIFY.search(text))


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
