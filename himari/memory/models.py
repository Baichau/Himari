"""Memory records and categories."""

from dataclasses import dataclass

CATEGORIES = (
    "preferences",
    "personal_context",
    "projects",
    "decisions",
    "workflows",
    "conversation_summaries",
    "activity",
)


@dataclass(frozen=True)
class Memory:
    id: str
    text: str
    category: str
    project: str | None
    source: str
    created: float
    approved: bool
    score: float = 0.0
    reason: str = ""

    @classmethod
    def from_row(cls, row):
        keys = row.keys()
        category = row["category"] if "category" in keys and row["category"] else "personal_context"
        return cls(
            id=row["id"],
            text=row["text"],
            category=category,
            project=row["project"] if "project" in keys else None,
            source=row["source"],
            created=row["created"],
            approved=bool(row["approved"]),
            score=float(row["score"]) if "score" in keys and row["score"] is not None else 0.0,
            reason=str(row["reason"]) if "reason" in keys and row["reason"] else "",
        )