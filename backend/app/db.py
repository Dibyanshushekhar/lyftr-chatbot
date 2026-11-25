"""SQLite storage for sessions and messages (stdlib sqlite3, schema auto-created)."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    system_prompt TEXT,
    created_at TEXT NOT NULL
);
"""


def sqlite_path(url: str) -> str:
    """sqlite:////data/app.db -> /data/app.db ; sqlite:///./x.db -> ./x.db"""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError("DATABASE_URL must start with sqlite:///")
    return url[len(prefix):]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, url: str):
        self.path = sqlite_path(url)
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commit / rollback
                yield conn
        finally:
            conn.close()

    def ping(self) -> bool:
        try:
            with self._conn() as c:
                c.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def get_system_prompt(self, session_id: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT system_prompt FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return row["system_prompt"] if row else None

    def get_history(self, session_id: str) -> list[dict]:
        """Plain {role, content} dicts, oldest first (what is sent to the LLM)."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content FROM messages WHERE session_id=? ORDER BY id", (session_id,)
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def get_messages(self, session_id: str) -> list[dict] | None:
        """History for the API; None if the session does not exist."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content, metadata FROM messages WHERE session_id=? ORDER BY id", (session_id,)
            ).fetchall()
        if not rows:
            return None
        out = []
        for r in rows:
            m = {"role": r["role"], "content": r["content"]}
            if r["metadata"]:
                m["metadata"] = json.loads(r["metadata"])
            out.append(m)
        return out

    def add_exchange(self, session_id: str, user_msg: str, reply: str, metadata: dict,
                     system_prompt: str | None) -> None:
        """Atomically store the user message + assistant reply (only called on success)."""
        now = _now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO sessions(session_id, system_prompt, created_at) VALUES(?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET system_prompt=excluded.system_prompt",
                (session_id, system_prompt, now),
            )
            c.execute(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
                (session_id, "user", user_msg, None, now),
            )
            c.execute(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
                (session_id, "assistant", reply, json.dumps(metadata), _now()),
            )
