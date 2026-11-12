"""Bounded memory retrieval ranked by token relevance."""

import re

from .. import db
from .manager import _LIST_COLUMNS, MemoryManager
from .models import Memory

TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
MAX_CANDIDATES = 200


def retrieve(query, limit=8, token_budget=800):
    """Return relevant memories within a bounded relevance/token budget."""
    if not MemoryManager().enabled():
        return []
    tokens = [
        token.casefold()
        for token in TOKEN_PATTERN.findall(query or "")
        if len(token) > 2
    ][:8]
    if not tokens:
        return []
    like_clause = " OR ".join(["text LIKE ?"] * len(tokens))
    params = [f"%{token}%" for token in tokens]
    with db._lock, db.conn() as connection:
        rows = connection.execute(
            f"SELECT {_LIST_COLUMNS} FROM memories "
            f"WHERE approved=1 AND ({like_clause}) "
            f"ORDER BY created DESC LIMIT ?",
            (*params, MAX_CANDIDATES),
        ).fetchall()
    ranked = []
    for row in rows:
        lowered = row["text"].casefold()
        score = sum(lowered.count(token) for token in tokens)
        if score:
            ranked.append((score, Memory.from_row(row)))
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = []
    used = 0
    for _, memory in ranked:
        cost = max(len(memory.text) // 4, 1)
        if used + cost > token_budget:
            continue
        selected.append(memory)
        used += cost
        if len(selected) >= limit:
            break
    return selected