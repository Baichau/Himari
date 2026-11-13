"""Optional local embeddings for hybrid memory retrieval.

Semantic ranking is used only when `memory.embedding_model` names a model the
user already installed in their local Ollama instance. Nothing is downloaded
and a missing model, stopped server, or malformed response falls back to the
keyword ranker with a warning.
"""

import logging
import math

from .. import db
from ..config import load

log = logging.getLogger("himari.memory")
MIN_SEMANTIC_SCORE = 0.35


def configured_model():
    config = load()
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    return str(memory.get("embedding_model") or "").strip()


def _client():
    import ollama

    return ollama.Client(host=load()["ollama"]["host"])


def embed(texts, model):
    response = _client().embed(model=model, input=list(texts))
    raw = response.get("embeddings") if hasattr(response, "get") else None
    vectors = [[float(value) for value in vector] for vector in (raw or [])]
    if len(vectors) != len(texts):
        raise ValueError("The embedding model returned an unexpected number of vectors.")
    return vectors


def _cosine(first, second):
    if not first or not second or len(first) != len(second):
        return 0.0
    dot = sum(left * right for left, right in zip(first, second))
    left_norm = math.sqrt(sum(value * value for value in first))
    right_norm = math.sqrt(sum(value * value for value in second))
    if not left_norm or not right_norm:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def semantic_scores(query, rows, model):
    """Return `{memory_id: cosine}` for the supplied rows, caching vectors."""
    if not rows:
        return {}
    stored = db.memory_vectors(model)
    missing = {
        row["id"]: str(row.get("text") or "")
        for row in rows
        if row["id"] not in stored and str(row.get("text") or "").strip()
    }
    if missing:
        identifiers = list(missing)
        vectors = embed([missing[identifier] for identifier in identifiers], model)
        fresh = dict(zip(identifiers, vectors))
        db.store_memory_vectors(model, fresh)
        stored.update(fresh)
    query_vector = embed([query], model)[0]
    return {
        row["id"]: _cosine(query_vector, stored[row["id"]])
        for row in rows
        if row["id"] in stored
    }
