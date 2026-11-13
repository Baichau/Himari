import re
import sqlite3, json, time, uuid, threading
from .config import APP_DIR
DB=APP_DIR/"himari.db"
_lock=threading.Lock()
def conn():
    APP_DIR.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB,timeout=10); c.row_factory=sqlite3.Row
    c.executescript("""PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, session TEXT, role TEXT, content TEXT, ts REAL);
    CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY, text TEXT UNIQUE, source TEXT, created REAL, approved INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, tool TEXT, args TEXT, result TEXT, ts REAL, approved INTEGER);
    CREATE TABLE IF NOT EXISTS summaries(id TEXT PRIMARY KEY, session TEXT, text TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS memory_vectors(memory_id TEXT, model TEXT, vector TEXT, created REAL, PRIMARY KEY(memory_id,model));
    CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session,ts);
    CREATE INDEX IF NOT EXISTS idx_mem_created ON memories(created);
    CREATE INDEX IF NOT EXISTS idx_summary_session ON summaries(session,created);""")
    return c
def add_message(session,role,content):
    with _lock, conn() as c:
        c.execute("INSERT INTO messages VALUES(?,?,?,?,?)",(str(uuid.uuid4()),session,role,content,time.time()))
def history(session,limit=60,max_chars=9000):
    with _lock, conn() as c:
        rows=c.execute("SELECT role,content FROM messages WHERE session=? ORDER BY ts DESC LIMIT ?",(session,limit)).fetchall()
    kept=[]; total=0
    for row in rows:
        content=str(row["content"] or "")
        if kept and total+len(content)>max_chars:
            break
        kept.append({"role":row["role"],"content":content})
        total+=len(content)
    return list(reversed(kept))


def message_count(session):
    with _lock, conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE session=?", (session,)
        ).fetchone()
    return int(row["n"] or 0)


def messages_detailed(session, limit=200):
    with _lock, conn() as c:
        rows = c.execute(
            "SELECT role,content,ts FROM messages WHERE session=? ORDER BY ts DESC LIMIT ?",
            (session, limit),
        ).fetchall()
    return [
        {"role": row["role"], "content": row["content"], "ts": row["ts"]}
        for row in reversed(rows)
    ]


def sessions(limit=40):
    with _lock, conn() as c:
        rows = c.execute(
            """
            SELECT m.session AS session,
                   MAX(m.ts) AS updated,
                   COUNT(*) AS messages,
                   (
                       SELECT content FROM messages first
                       WHERE first.session = m.session AND first.role = 'user'
                       ORDER BY first.ts ASC LIMIT 1
                   ) AS title
            FROM messages m
            GROUP BY m.session
            ORDER BY updated DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        title = re.sub(r"\s+", " ", str(row["title"] or "")).strip()
        result.append({
            "session": row["session"],
            "updated": row["updated"],
            "messages": row["messages"],
            "title": title[:64] or "Untitled chat",
        })
    return result

def summary_for_session(session, limit=12):
    with _lock, conn() as c:
        row = c.execute(
            "SELECT text FROM summaries WHERE session=? "
            "ORDER BY created DESC, rowid DESC LIMIT 1",
            (session,),
        ).fetchone()
        if row:
            return row["text"]
        rows = c.execute(
            "SELECT role, content FROM messages WHERE session=? ORDER BY ts DESC LIMIT ?",
            (session, limit),
        ).fetchall()
        recent = [f"{r['role']}: {r['content']}" for r in reversed(rows)]
        if not recent:
            return ""
        return " | ".join(recent[-8:])

SUMMARY_MERGE_SIMILARITY = 0.6
MIN_MERGE_TOKENS = 6


def _summary_tokens(text):
    return set(re.findall(r"[^\W_]{3,}", str(text or "").casefold()))


def _summary_similarity(left, right):
    left_tokens = _summary_tokens(left)
    right_tokens = _summary_tokens(right)
    if min(len(left_tokens), len(right_tokens)) < MIN_MERGE_TOKENS:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _merge_summary_text(old, new):
    sentences = []
    seen = set()
    for chunk in re.split(r"(?<=[.!?])\s+|\n+", f"{old} {new}".strip()):
        sentence = chunk.strip()
        if not sentence:
            continue
        key = re.sub(r"\s+", " ", sentence.casefold()).rstrip(".!?")
        if key in seen:
            continue
        seen.add(key)
        sentences.append(
            sentence if sentence.endswith((".", "!", "?")) else sentence + "."
        )
    return " ".join(sentences)


def save_summary(session, text, keep=10):
    summary = (text or "").strip()
    if not summary:
        return None
    with _lock, conn() as c:
        newest = c.execute(
            "SELECT id, text FROM summaries WHERE session=? "
            "ORDER BY created DESC, rowid DESC LIMIT 1",
            (session,),
        ).fetchone()
        if newest and _summary_similarity(newest["text"], summary) >= SUMMARY_MERGE_SIMILARITY:
            merged = _merge_summary_text(newest["text"], summary)
            c.execute(
                "UPDATE summaries SET text=?, created=? WHERE id=?",
                (merged, time.time(), newest["id"]),
            )
            return merged
        c.execute("INSERT INTO summaries VALUES(?,?,?,?)", (str(uuid.uuid4()), session, summary, time.time()))
        c.execute(
            "DELETE FROM summaries WHERE session=? AND rowid NOT IN ("
            "SELECT rowid FROM summaries WHERE session=? "
            "ORDER BY created DESC, rowid DESC LIMIT ?)",
            (session, session, max(1, int(keep))),
        )
    return summary

def search_messages(q,limit=20):
    with _lock, conn() as c:
        return [dict(r) for r in c.execute("SELECT session,role,content,ts FROM messages WHERE content LIKE ? ORDER BY ts DESC LIMIT ?",(f"%{q}%",limit))]
def clear_session(session):
    with _lock, conn() as c:
        c.execute("DELETE FROM messages WHERE session=?", (session,))
        c.execute("DELETE FROM summaries WHERE session=?", (session,))
def clear_all_sessions():
    with _lock, conn() as c:
        c.execute("DELETE FROM messages")
        c.execute("DELETE FROM summaries")
def add_memory(text,source="user",approved=1):
    if not isinstance(text, str):
        raise TypeError("Memory text must be a string.")
    text=text.strip()
    if not text: return None
    with _lock, conn() as c:
        normalized = text.casefold()
        existing = c.execute("SELECT id, text, approved FROM memories").fetchall()
        for row in existing:
            if row["text"].strip().casefold() == normalized:
                if approved and not row["approved"]:
                    c.execute(
                        "UPDATE memories SET approved=1, source=? WHERE id=?",
                        (source, row["id"]),
                    )
                return row["id"]
        memory_id = str(uuid.uuid4())
        cursor = c.execute(
            "INSERT OR IGNORE INTO memories(id,text,source,created,approved) VALUES(?,?,?,?,?)",
            (memory_id,text,source,time.time(),int(bool(approved))),
        )
        return memory_id if cursor.rowcount else None


_MEMORY_REQUEST = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"remember\s+that|"
    r"remember\s*:\s*|"
    r"keep\s+in\s+mind\s+that|"
    r"don'?t\s+forget\s+that|"
    r"note\s+that|"
    r"запомни\s*,?\s*(?:что\s*)?"
    r")(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_SENSITIVE_MEMORY = re.compile(
    r"\b(?:password|passphrase|pin|secret|api[\s_-]?key|token|"
    r"one[-\s]?time code|verification code|credit card|ssn|"
    r"phone|email|address|passport|bank account|date of birth|"
    r"парол\w*|пин-код|секрет\w*|токен\w*|код подтверждения|"
    r"номер карты|номер телефона|телефон\w*|адрес\w*|домашний адрес|дата рождения|паспорт)\b|"
    r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|"
    r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",
    re.IGNORECASE,
)
_TEMPORARY_MEMORY = re.compile(
    r"\b(?:today|tomorrow|tonight|right now|for now|currently|at present|this week|this month|"
    r"сегодня|завтра|сейчас|временно|пока что|на этой неделе)\b",
    re.IGNORECASE,
)


def memory_is_sensitive(text):
    return bool(_SENSITIVE_MEMORY.search(text or ""))


def suggest_memory(message):
    if not isinstance(message, str):
        return None
    match = _MEMORY_REQUEST.match(message)
    if not match:
        return None
    candidate = match.group(1).strip()
    if (
        not candidate
        or len(candidate) > 240
        or _SENSITIVE_MEMORY.search(candidate)
        or _TEMPORARY_MEMORY.search(candidate)
    ):
        return None
    return add_memory(candidate, source="suggestion", approved=0)


def memory_suggestions(limit=200):
    with _lock, conn() as c:
        return [
            dict(row) for row in c.execute(
                "SELECT * FROM memories WHERE approved=0 ORDER BY created DESC LIMIT ?",
                (limit,),
            )
        ]
def memories(limit=200):
    with _lock, conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM memories WHERE approved=1 ORDER BY created DESC LIMIT ?",(limit,))]

def memory_counts():
    with _lock, conn() as c:
        approved = c.execute(
            "SELECT COUNT(*) FROM memories WHERE approved=1"
        ).fetchone()[0]
        suggestions = c.execute(
            "SELECT COUNT(*) FROM memories WHERE approved=0"
        ).fetchone()[0]
    return {"approved": approved, "suggestions": suggestions}

def relevant_memories(query, limit=8):
    q = (query or "").strip()
    if not q:
        return []
    from .memory.scoring import rank

    return rank(memories(limit=200), q, limit=limit)

def delete_memory(mid):
    with _lock, conn() as c:
        c.execute("DELETE FROM memory_vectors WHERE memory_id=?",(mid,))
        c.execute("DELETE FROM memories WHERE id=?",(mid,))
def update_memory(mid,text):
    with _lock, conn() as c:
        c.execute("DELETE FROM memory_vectors WHERE memory_id=?",(mid,))
        c.execute("UPDATE memories SET text=? WHERE id=?",(text,mid))
def memory_vectors(model):
    with _lock, conn() as c:
        rows = c.execute(
            "SELECT memory_id,vector FROM memory_vectors WHERE model=?", (model,)
        ).fetchall()
    vectors = {}
    for row in rows:
        try:
            vectors[row["memory_id"]] = [float(value) for value in json.loads(row["vector"])]
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return vectors
def store_memory_vectors(model, vectors):
    now = time.time()
    with _lock, conn() as c:
        for memory_id, vector in vectors.items():
            c.execute(
                "INSERT OR REPLACE INTO memory_vectors(memory_id,model,vector,created) VALUES(?,?,?,?)",
                (memory_id, model, json.dumps([float(v) for v in vector]), now),
            )
def forget_memory_vector(memory_id):
    with _lock, conn() as c:
        c.execute("DELETE FROM memory_vectors WHERE memory_id=?", (memory_id,))
def log_action(tool,args,result,approved):
    with _lock, conn() as c:
        c.execute("INSERT INTO actions VALUES(?,?,?,?,?,?)",(str(uuid.uuid4()),tool,json.dumps(args,default=str),str(result)[:4000],time.time(),int(approved)))
def recent_actions(limit=50):
    with _lock, conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM actions ORDER BY ts DESC LIMIT ?",(limit,))]
