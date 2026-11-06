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
    CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session,ts);
    CREATE INDEX IF NOT EXISTS idx_mem_created ON memories(created);
    CREATE INDEX IF NOT EXISTS idx_summary_session ON summaries(session,created);""")
    return c
def add_message(session,role,content):
    with _lock, conn() as c:
        c.execute("INSERT INTO messages VALUES(?,?,?,?,?)",(str(uuid.uuid4()),session,role,content,time.time()))
def history(session,limit=60):
    with _lock, conn() as c:
        rows=c.execute("SELECT role,content FROM messages WHERE session=? ORDER BY ts DESC LIMIT ?",(session,limit)).fetchall()
    return [{"role":r["role"],"content":r["content"]} for r in reversed(rows)]

def summary_for_session(session, limit=12):
    with _lock, conn() as c:
        row = c.execute(
            "SELECT text FROM summaries WHERE session=? ORDER BY created DESC LIMIT 1",
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

def save_summary(session, text):
    summary = (text or "").strip()
    if not summary:
        return None
    with _lock, conn() as c:
        c.execute("INSERT INTO summaries VALUES(?,?,?,?)", (str(uuid.uuid4()), session, summary, time.time()))
    return summary

def search_messages(q,limit=20):
    with _lock, conn() as c:
        return [dict(r) for r in c.execute("SELECT session,role,content,ts FROM messages WHERE content LIKE ? ORDER BY ts DESC LIMIT ?",(f"%{q}%",limit))]
def clear_session(session):
    with _lock, conn() as c:
        c.execute("DELETE FROM messages WHERE session=?", (session,))
        c.execute("DELETE FROM summaries WHERE session=?", (session,))
def add_memory(text,source="user",approved=1):
    text=text.strip()
    if not text: return None
    with _lock, conn() as c:
        try: c.execute("INSERT OR IGNORE INTO memories VALUES(?,?,?,?,?)",(str(uuid.uuid4()),text,source,time.time(),approved))
        except Exception: pass
def memories(limit=200):
    with _lock, conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM memories WHERE approved=1 ORDER BY created DESC LIMIT ?",(limit,))]

def relevant_memories(query, limit=8):
    q = (query or "").strip()
    if not q:
        return memories(limit=limit)
    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", q) if len(t) > 2]
    if not tokens:
        return memories(limit=limit)
    rows = memories(limit=200)
    ranked = []
    for item in rows:
        text = (item.get("text") or "").lower()
        score = 0
        for token in tokens:
            score += text.count(token)
            if token in text:
                score += 1
        if score > 0:
            ranked.append((score, item))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in ranked[:limit]]

def delete_memory(mid):
    with _lock, conn() as c: c.execute("DELETE FROM memories WHERE id=?",(mid,))
def update_memory(mid,text):
    with _lock, conn() as c: c.execute("UPDATE memories SET text=? WHERE id=?",(text,mid))
def log_action(tool,args,result,approved):
    with _lock, conn() as c:
        c.execute("INSERT INTO actions VALUES(?,?,?,?,?,?)",(str(uuid.uuid4()),tool,json.dumps(args,default=str),str(result)[:4000],time.time(),int(approved)))
def recent_actions(limit=50):
    with _lock, conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM actions ORDER BY ts DESC LIMIT ?",(limit,))]
