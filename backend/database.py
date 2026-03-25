import sqlite3
from datetime import datetime, timezone

DB_PATH = "coach.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── 마이그레이션 헬퍼 ──────────────────────────────────────────────────────────
# SQLite는 ADD COLUMN IF NOT EXISTS 미지원 → PRAGMA로 직접 확인

def _add_col_if_missing(conn, table: str, column: str, col_def: str):
    """테이블에 컬럼이 없을 때만 ALTER TABLE로 추가한다."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def init_db():
    with get_conn() as conn:
        # ── 기존 테이블 (유지) ──────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                mission     TEXT    NOT NULL,
                result      TEXT    NOT NULL,
                reason      TEXT,
                ai_response TEXT,
                created_at  TEXT    NOT NULL
            )
        """)

        # ── 테스트 로그 테이블: 신규 생성 시 컬럼 전부 포함 ─────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkin_logs (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at     TEXT NOT NULL,
                mission        TEXT NOT NULL,
                result         TEXT NOT NULL,
                reason_text    TEXT,
                ai_response    TEXT,
                model_name     TEXT,
                prompt_version TEXT NOT NULL DEFAULT 'v1',
                expected_label TEXT,
                memo           TEXT,
                quality_label  TEXT,
                failure_type   TEXT,
                reviewer_note  TEXT
            )
        """)

        # ── 기존 DB에 테이블이 이미 있으면 컬럼만 안전하게 추가 ────────────────
        _add_col_if_missing(conn, "checkin_logs", "quality_label", "TEXT")
        _add_col_if_missing(conn, "checkin_logs", "failure_type",  "TEXT")
        _add_col_if_missing(conn, "checkin_logs", "reviewer_note", "TEXT")

        # ── 대화 히스토리 테이블 ────────────────────────────────────────────────
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


# ── 기존 함수 (유지) ─────────────────────────────────────────────────────────

def save_log(mission: str, result: str, reason: str | None, ai_response: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO logs (mission, result, reason, ai_response, created_at) VALUES (?,?,?,?,?)",
            (mission, result, reason, ai_response, now),
        )
        conn.commit()
        return cur.lastrowid


def fetch_logs(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── checkin_logs CRUD ────────────────────────────────────────────────────────

def save_checkin_log(
    mission: str,
    result: str,
    reason_text: str | None,
    ai_response: str,
    model_name: str,
    prompt_version: str = "v1",
    expected_label: str | None = None,
    memo: str | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO checkin_logs
                (created_at, mission, result, reason_text, ai_response,
                 model_name, prompt_version, expected_label, memo)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (now, mission, result, reason_text, ai_response,
             model_name, prompt_version, expected_label, memo),
        )
        conn.commit()
        return cur.lastrowid


def fetch_checkin_logs(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM checkin_logs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── conversations CRUD ────────────────────────────────────────────────────────

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


def update_review(
    log_id: int,
    quality_label: str | None,
    failure_type: str | None,
    reviewer_note: str | None,
) -> bool:
    """quality_label / failure_type / reviewer_note 를 덮어쓴다. 행이 없으면 False."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE checkin_logs
               SET quality_label = ?,
                   failure_type  = ?,
                   reviewer_note = ?
             WHERE id = ?
            """,
            (quality_label, failure_type, reviewer_note, log_id),
        )
        conn.commit()
        return cur.rowcount > 0
