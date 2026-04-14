import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS session_profiles (
                    session_id    TEXT PRIMARY KEY,
                    student_id    INTEGER,
                    student_name  TEXT,
                    db_session_id INTEGER,
                    created_at    TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        conn.commit()


# ── 학생 본인 확인 (students 테이블) ───────────────────────────────────────────

def get_student_by_credentials(student_name: str, phone_last4: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM students WHERE student_name = %s AND is_active = TRUE",
                (student_name,),
            )
            rows = cur.fetchall()
    for r in rows:
        phone = str(r["phone_number"]).replace("-", "")
        if phone[-4:] == phone_last4:
            return dict(r)
    return None


# ── 채팅 세션 (chat_sessions 테이블) ──────────────────────────────────────────

def create_chat_session(student_id: int) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_sessions (student_id, started_at) VALUES (%s, NOW()) RETURNING session_id",
                (student_id,),
            )
            db_session_id = cur.fetchone()[0]
        conn.commit()
    return db_session_id


def save_profile(session_id: str, student_id: int, student_name: str, db_session_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO session_profiles (session_id, student_id, student_name, db_session_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE
                    SET student_id    = EXCLUDED.student_id,
                        student_name  = EXCLUDED.student_name,
                        db_session_id = EXCLUDED.db_session_id
                """,
                (session_id, student_id, student_name, db_session_id),
            )
        conn.commit()


def fetch_profile(session_id: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT student_id, student_name, db_session_id FROM session_profiles WHERE session_id = %s",
                (session_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


# ── 채팅 메시지 (chat_messages 테이블) ────────────────────────────────────────

def save_message(session_id: str, role: str, content: str, detected_function: str | None = None) -> int:
    profile = fetch_profile(session_id)
    if not profile:
        return 0
    speaker = "student" if role == "user" else "ai"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_messages
                    (session_id, student_id, speaker, message_text, detected_function)
                VALUES (%s, %s, %s, %s, %s) RETURNING message_id
                """,
                (profile["db_session_id"], profile["student_id"], speaker, content, detected_function),
            )
            row_id = cur.fetchone()[0]
        conn.commit()
    return row_id


def fetch_messages(session_id: str) -> list[dict]:
    profile = fetch_profile(session_id)
    if not profile:
        return []
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT speaker, message_text, created_at FROM chat_messages WHERE session_id = %s ORDER BY message_id",
                (profile["db_session_id"],),
            )
            rows = cur.fetchall()
    return [
        {
            "role": "user" if r["speaker"] == "student" else "assistant",
            "content": r["message_text"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


def delete_messages(session_id: str) -> int:
    profile = fetch_profile(session_id)
    if not profile:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chat_messages WHERE session_id = %s", (profile["db_session_id"],))
            count = cur.rowcount
            cur.execute(
                "UPDATE chat_sessions SET ended_at = NOW() WHERE session_id = %s",
                (profile["db_session_id"],),
            )
        conn.commit()
    return count


# ── 오늘의 미션 (student_daily_missions + missions 테이블) ─────────────────────

def get_student_mission_db(student_id: int, today: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT m.mission_id, m.mission_name, m.category, m.difficulty,
                       m.mission_description, sdm.status
                FROM student_daily_missions sdm
                JOIN missions m ON sdm.mission_id = m.mission_id
                WHERE sdm.student_id = %s AND sdm.assigned_date = %s
                """,
                (student_id, today),
            )
            row = cur.fetchone()
    return dict(row) if row else None


# ── 학생 정보 조회 (students 테이블) ──────────────────────────────────────────

def get_student_info_db(student_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM students WHERE student_id = %s",
                (student_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


# ── 미션 결과 저장 (checkin_log 테이블) ───────────────────────────────────────

def save_mission_result(
    student_id: int,
    student_name: str,
    mission_id: int | None,
    mission_name: str,
    status: str,
    result_reason: str,
    ai_response: str,
    session_id: str,
    detected_function: str = "submit_mission_result",
) -> int:
    today = datetime.now(timezone.utc).date()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO checkin_log
                    (student_id, mission_id, checkin_date, mission_result,
                     result_reason, ai_response, function_called,
                     sheet_update_status, created_at, last_updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW(), NOW())
                RETURNING checkin_id
                """,
                (student_id, mission_id, today, status,
                 result_reason, ai_response, detected_function),
            )
            row_id = cur.fetchone()[0]
        conn.commit()
    return row_id


def mark_synced(result_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE checkin_log SET sheet_update_status = 'synced', last_updated_at = NOW() WHERE checkin_id = %s",
                (result_id,),
            )
        conn.commit()


# ── Function 감지 (questions 테이블 기반) ──────────────────────────────────────

def detect_function_from_db(user_message: str) -> str | None:
    """
    questions 테이블 텍스트 오버랩으로 function 감지.
    (추후 embedding 기반 시맨틱 검색으로 업그레이드 가능)
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT q.question_text, f.function_name
                FROM questions q
                JOIN functions f ON q.function_id = f.function_id
                WHERE f.is_active = TRUE
                """,
            )
            rows = cur.fetchall()

    best_fn = None
    best_score = 0
    msg_chars = set(user_message)
    for r in rows:
        score = len(set(r["question_text"]) & msg_chars)
        if score > best_score:
            best_score = score
            best_fn = r["function_name"]

    return best_fn if best_score >= 3 else None
