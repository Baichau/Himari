"""Persistent local memories in the existing SQLite database.

Adds category/project/normalized columns via an in-place migration that keeps
existing rows intact. Passwords, tokens and short-lived facts are rejected.
"""

import time
import uuid

from .. import db
from ..config import load as load_config
from ..db import _SENSITIVE_MEMORY, _TEMPORARY_MEMORY
from .models import CATEGORIES, Memory

MAX_MEMORY_LENGTH = 500
_LIST_COLUMNS = "id,text,source,created,approved,category,project"


class MemoryManager:
    def __init__(self):
        self._ensure_schema()

    def _ensure_schema(self):
        with db._lock, db.conn() as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(memories)").fetchall()
            }
            if "category" not in columns:
                connection.execute(
                    "ALTER TABLE memories ADD COLUMN category TEXT DEFAULT 'personal_context'"
                )
            if "project" not in columns:
                connection.execute("ALTER TABLE memories ADD COLUMN project TEXT")
            if "normalized" not in columns:
                connection.execute("ALTER TABLE memories ADD COLUMN normalized TEXT")
            pending = connection.execute(
                "SELECT id, text FROM memories WHERE normalized IS NULL"
            ).fetchall()
            for row in pending:
                connection.execute(
                    "UPDATE memories SET normalized=? WHERE id=?",
                    (normalize(row["text"]), row["id"]),
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_category ON memories(category)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_normalized ON memories(normalized)"
            )

    def enabled(self):
        config = load_config()
        privacy = config.get("privacy", {}) if isinstance(config, dict) else {}
        return bool(privacy.get("memory_enabled", True))

    def add(self, text, category="personal_context", project=None, source="user", approved=True):
        if not self.enabled():
            return None
        if not isinstance(text, str):
            raise TypeError("Memory text must be a string.")
        text = text.strip()
        if not text or len(text) > MAX_MEMORY_LENGTH:
            return None
        if category not in CATEGORIES:
            raise ValueError(f"Unknown memory category: {category}")
        if _SENSITIVE_MEMORY.search(text) or _TEMPORARY_MEMORY.search(text):
            return None
        normalized = normalize(text)
        with db._lock, db.conn() as connection:
            existing = connection.execute(
                "SELECT id FROM memories WHERE normalized=? LIMIT 1", (normalized,)
            ).fetchone()
            if existing:
                if approved:
                    connection.execute(
                        "UPDATE memories SET approved=1 WHERE id=?", (existing["id"],)
                    )
                return existing["id"]
            memory_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO memories(id,text,source,created,approved,category,project,normalized) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    memory_id, text, source, time.time(), int(bool(approved)),
                    category, project, normalized,
                ),
            )
            return memory_id

    def get(self, memory_id):
        with db._lock, db.conn() as connection:
            row = connection.execute(
                f"SELECT {_LIST_COLUMNS} FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
        return Memory.from_row(row) if row else None

    def list_memories(self, category=None, project=None, include_suggestions=False, limit=200):
        clauses = []
        params = []
        if not include_suggestions:
            clauses.append("approved=1")
        if category:
            clauses.append("category=?")
            params.append(category)
        if project:
            clauses.append("project=?")
            params.append(project)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with db._lock, db.conn() as connection:
            rows = connection.execute(
                f"SELECT {_LIST_COLUMNS} FROM memories {where} ORDER BY created DESC LIMIT ?",
                (*params, int(limit)),
            ).fetchall()
        return [Memory.from_row(row) for row in rows]

    def update(self, memory_id, text=None, category=None, project=None):
        if text is not None:
            if not isinstance(text, str) or not text.strip():
                return False
            text = text.strip()
            if len(text) > MAX_MEMORY_LENGTH:
                return False
            if _SENSITIVE_MEMORY.search(text):
                return False
        if category is not None and category not in CATEGORIES:
            raise ValueError(f"Unknown memory category: {category}")
        with db._lock, db.conn() as connection:
            if text is not None:
                connection.execute(
                    "UPDATE memories SET text=?, normalized=? WHERE id=?",
                    (text, normalize(text), memory_id),
                )
            if category is not None:
                connection.execute(
                    "UPDATE memories SET category=? WHERE id=?", (category, memory_id)
                )
            if project is not None:
                connection.execute(
                    "UPDATE memories SET project=? WHERE id=?", (project, memory_id)
                )
            row = connection.execute(
                "SELECT id FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
        return row is not None

    def approve(self, memory_id):
        with db._lock, db.conn() as connection:
            connection.execute("UPDATE memories SET approved=1 WHERE id=?", (memory_id,))

    def delete(self, memory_id):
        with db._lock, db.conn() as connection:
            connection.execute("DELETE FROM memories WHERE id=?", (memory_id,))


def normalize(text):
    return " ".join(str(text).split()).casefold()