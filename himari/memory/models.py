"""Memory records and categories."""

from dataclasses import dataclass

CATEGORIES = (
    "preferences",
    "personal_context",
    "projects",
    "decisions",
    "workflows",
    "conversation_summaries",
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
        )