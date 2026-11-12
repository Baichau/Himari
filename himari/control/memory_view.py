"""Memory management helpers for the Control Center."""

from .. import db


def memory_rows(query="", limit=200):
    needle = str(query or "").strip().casefold()
    rows = []
    for memory in db.memories(limit=limit):
        text = str(memory.get("text", ""))
        if needle and needle not in text.casefold():
            continue
        rows.append({
            "id": memory.get("id"),
            "text": text,
            "source": memory.get("source", "user"),
            "category": memory.get("category") or "uncategorized",
            "project": memory.get("project"),
            "created": memory.get("created"),
        })
    return rows


def suggestion_rows(limit=200):
    rows = []
    for memory in db.memory_suggestions(limit=limit):
        rows.append({
            "id": memory.get("id"),
            "text": str(memory.get("text", "")),
            "source": memory.get("source", "suggestion"),
            "category": memory.get("category") or "uncategorized",
        })
    return rows


def stats():
    counts = db.memory_counts()
    return {
        "approved": counts.get("approved", 0),
        "suggestions": counts.get("suggestions", 0),
    }


def approve(memory_id):
    suggestions = {item["id"]: item for item in db.memory_suggestions(limit=1000)}
    suggestion = suggestions.get(memory_id)
    if not suggestion:
        return False
    db.add_memory(suggestion["text"], source="user", approved=1)
    remaining = {item["id"] for item in db.memory_suggestions(limit=1000)}
    if memory_id in remaining:
        db.delete_memory(memory_id)
    return True


def reject(memory_id):
    db.delete_memory(memory_id)
    return True


def delete(memory_id):
    db.delete_memory(memory_id)
    return True


def update(memory_id, text):
    text = str(text or "").strip()
    if not text:
        raise ValueError("Memory text cannot be empty.")
    db.update_memory(memory_id, text)
    return True
