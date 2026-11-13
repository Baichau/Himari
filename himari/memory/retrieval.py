"""Bounded hybrid memory retrieval with relevance, recency and importance."""

import logging

from .. import db
from . import embeddings
from .manager import MemoryManager
from .models import Memory
from .scoring import rank

log = logging.getLogger("himari.memory")

MAX_CANDIDATES = 200


def retrieve(query, limit=8, token_budget=800, project=None):
    """Return relevant memories within a bounded token budget.

    Each returned ``Memory`` carries ``score`` and ``reason`` so callers can
    explain why it was selected without exposing private reasoning traces.
    """
    if not MemoryManager().enabled():
        return []
    if not str(query or "").strip():
        return []
    rows = db.memories(limit=MAX_CANDIDATES)
    semantic = None
    model = embeddings.configured_model()
    if model:
        try:
            semantic = embeddings.semantic_scores(query, rows, model)
        except Exception as exc:
            log.warning(
                "Semantic memory retrieval is unavailable (%s); using keyword ranking.", exc
            )
    ranked = rank(
        rows,
        query,
        limit=limit,
        token_budget=token_budget,
        project=project,
        semantic=semantic,
    )
    memories = [Memory.from_row(row) for row in ranked]
    if memories:
        log.debug(
            "Retrieved %d memory item(s): %s",
            len(memories),
            "; ".join(f"{item.score:.2f} {item.reason}" for item in memories),
        )
    return memories
