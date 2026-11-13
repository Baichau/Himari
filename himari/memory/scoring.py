"""Relevance, recency and importance scoring shared by memory retrieval.

The scorer is deterministic and local: token overlap, phrase matches, category
importance, age, and an optional project boost. Every selected row keeps a short
reason string so callers can explain why it was retrieved.
"""

import re
import time

TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
MAX_QUERY_TOKENS = 8
PHRASE_BOOST = 2.0
COVERAGE_WEIGHT = 3.0
FREQUENCY_CAP = 3
RECENCY_WEIGHT = 0.75
RECENCY_HALF_LIFE_DAYS = 90.0
PROJECT_BOOST = 0.35
SEMANTIC_WEIGHT = 2.0
SEMANTIC_MIN_SCORE = 0.35
NEAR_DUPLICATE_JACCARD = 0.75

CATEGORY_WEIGHTS = {
    "preferences": 1.15,
    "personal_context": 1.0,
    "projects": 1.1,
    "decisions": 1.05,
    "workflows": 1.0,
    "conversation_summaries": 0.9,
}


def tokens(text):
    return [
        token.casefold()
        for token in TOKEN_PATTERN.findall(str(text or ""))
        if len(token) > 2
    ]


def normalize(text):
    return " ".join(str(text or "").split()).casefold()


def _recency(created, now):
    if not created:
        return 0.5
    try:
        age_days = max(0.0, (now - float(created)) / 86400.0)
    except (TypeError, ValueError):
        return 0.5
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def score(query, text, category=None, created=None, project=None,
          row_project=None, now=None, semantic=None):
    """Return ``(score, reason)``; zero means the row does not match."""
    query_tokens = tokens(query)[:MAX_QUERY_TOKENS]
    if not query_tokens:
        return 0.0, ""
    haystack = normalize(text)
    if not haystack:
        return 0.0, ""
    haystack_tokens = set(tokens(haystack))
    overlap = [token for token in query_tokens if token in haystack_tokens]
    semantic_value = 0.0 if semantic is None else max(0.0, min(1.0, float(semantic)))
    semantic_match = semantic_value >= SEMANTIC_MIN_SCORE
    if not overlap and not semantic_match:
        return 0.0, ""
    coverage = len(overlap) / len(query_tokens)
    frequency = min(
        sum(haystack.count(token) for token in overlap), FREQUENCY_CAP
    )
    phrase = PHRASE_BOOST if " ".join(query_tokens) in haystack else 0.0
    importance = CATEGORY_WEIGHTS.get(category or "", 1.0)
    recency = _recency(created, now if now is not None else time.time())
    same_project = bool(project) and normalize(project) == normalize(row_project)
    relevance = coverage * COVERAGE_WEIGHT + frequency + phrase
    total = relevance * importance + recency * RECENCY_WEIGHT
    if semantic_match:
        total += semantic_value * SEMANTIC_WEIGHT
    if same_project:
        total += PROJECT_BOOST
    if overlap:
        reason = f"matched {len(overlap)}/{len(query_tokens)} terms"
    else:
        reason = "semantic match"
    if phrase:
        reason += ", exact phrase"
    if semantic_match:
        reason += f", semantic {semantic_value:.2f}"
    if same_project:
        reason += ", same project"
    return total, reason


def _jaccard(first, second):
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def _near_duplicate(first_text, second_text):
    first = set(tokens(first_text))
    second = set(tokens(second_text))
    if _jaccard(first, second) >= NEAR_DUPLICATE_JACCARD:
        return True
    short, long_ = sorted((normalize(first_text), normalize(second_text)), key=len)
    if len(short.split()) < 3:
        return False
    return long_.startswith(short + " ") and len(long_) - len(short) <= 40


def rank(rows, query, limit=8, token_budget=800, project=None, now=None,
         semantic=None):
    """Rank memory rows and return copies with ``score`` and ``reason``."""
    scored = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "")
        normalized = normalize(text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        value, reason = score(
            query,
            text,
            category=row.get("category"),
            created=row.get("created"),
            project=project,
            row_project=row.get("project"),
            now=now,
            semantic=(semantic or {}).get(row.get("id")),
        )
        if value <= 0:
            continue
        scored.append((value, reason, row))
    scored.sort(
        key=lambda item: (-item[0], -float(item[2].get("created") or 0))
    )
    selected = []
    selected_tokens = []
    used = 0
    try:
        budget = max(0, int(token_budget))
    except (TypeError, ValueError):
        budget = 800
    for value, reason, row in scored:
        text = str(row.get("text") or "")
        cost = max(len(text) // 4, 1)
        if used + cost > budget:
            continue
        row_tokens = set(tokens(text))
        if any(
            _jaccard(row_tokens, previous) >= NEAR_DUPLICATE_JACCARD
            for previous in selected_tokens
        ):
            continue
        selected.append({**row, "score": round(value, 3), "reason": reason})
        selected_tokens.append(row_tokens)
        used += cost
        if len(selected) >= max(1, int(limit)):
            break
    return selected


def is_near_duplicate(first_text, second_text):
    """Public helper used when deciding whether to merge a new memory."""
    if normalize(first_text) == normalize(second_text):
        return True
    return _near_duplicate(first_text, second_text)
