import sqlite3
from datetime import datetime, timezone

DB_PATH = "coach.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT    NOT NULL,
                role       TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                created_at TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_session
            ON conversations(session_id, id)
        """)
        conn.commit()


def save_message(session_id: str, role: str, content: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?,?,?,?)",
            (session_id, role, content, now),
        )
        conn.commit()
        return cur.lastrowid


def fetch_messages(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM conversations WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_messages(session_id: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()
        return cur.rowcount
