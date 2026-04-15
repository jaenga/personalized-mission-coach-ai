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


# ── 오늘의 미션 자동 배정 ─────────────────────────────────────────────────────

def _kst_today() -> str:
    """한국 시간(KST) 기준 오늘 날짜 반환."""
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")


def assign_daily_missions() -> int:
    """
    오늘(KST) 미션이 배정 안 된 학생에게 자동 배정
    - 최근 7일간 배정된 미션은 제외
    - 7일 기록 없으면 랜덤 1개 배정
    """
    today = _kst_today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO student_daily_missions (
                    student_id, mission_id, assigned_date, status, assigned_by
                )
                SELECT
                    s.student_id,
                    COALESCE(preferred.mission_id, fallback.mission_id) AS mission_id,
                    %s::date,
                    'assigned',
                    'system'
                FROM students s

                LEFT JOIN LATERAL (
                    SELECT m.mission_id
                    FROM missions m
                    WHERE m.is_active = TRUE
                      AND NOT EXISTS (
                          SELECT 1
                          FROM student_daily_missions sdm
                          WHERE sdm.student_id = s.student_id
                            AND sdm.assigned_date >= %s::date - INTERVAL '7 days'
                            AND sdm.assigned_date < %s::date
                            AND sdm.mission_id = m.mission_id
                      )
                    ORDER BY RANDOM()
                    LIMIT 1
                ) preferred ON TRUE

                LEFT JOIN LATERAL (
                    SELECT m.mission_id
                    FROM missions m
                    WHERE m.is_active = TRUE
                    ORDER BY RANDOM()
                    LIMIT 1
                ) fallback ON TRUE

                WHERE s.is_active = TRUE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM student_daily_missions sdm_today
                    WHERE sdm_today.student_id = s.student_id
                      AND sdm_today.assigned_date = %s::date
                )
            """, (today, today, today, today))
            assigned = cur.rowcount
        conn.commit()
    return assigned


# ── 오늘의 미션 (student_daily_missions + missions 테이블) ─────────────────────

def get_student_mission_db(student_id: int, today: str | None = None) -> dict | None:
    if today is None:
        today = _kst_today()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT m.mission_id, m.mission_name, m.category, m.difficulty,
                       m.mission_description, m.main_category, m.sub_category,
                       m.mission_location, m.reward_xp, m.mission_group,
                       m.mission_rule, sdm.status
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
    mission_id: int,
    status: str,
    result_reason: str | None = None,
    detected_function: str = "submit_mission_result",
) -> int:
    today = _kst_today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO checkin_log
                    (student_id, mission_id, checkin_date, mission_result,
                     result_reason, function_called,
                     sheet_update_status, created_at, last_updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending', NOW(), NOW())
                RETURNING checkin_id
                """,
                (student_id, mission_id, today, status,
                 result_reason, detected_function),
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


def cancel_last_checkin(student_id: int) -> bool:
    """오늘(KST) 해당 학생의 가장 최근 checkin_log 삭제. + student_daily_missions status를 assigned로 복원."""
    today = _kst_today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM checkin_log WHERE checkin_id = ("
                "  SELECT checkin_id FROM checkin_log"
                "  WHERE student_id = %s AND checkin_date = %s"
                "  ORDER BY created_at DESC LIMIT 1"
                ")",
                (student_id, today),
            )
            deleted = cur.rowcount > 0
            if deleted:
                cur.execute(
                    "UPDATE student_daily_missions SET status = 'assigned', updated_at = NOW() "
                    "WHERE student_id = %s AND assigned_date = %s",
                    (student_id, today),
                )
        conn.commit()
    return deleted


