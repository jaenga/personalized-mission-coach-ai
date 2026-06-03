import json
import os
import random
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from psycopg2.extras import Json
import threading
import time
import uuid
from datetime import date, datetime, timezone, timedelta
from dotenv import load_dotenv

from activity_keys import VALID_ACTIVITY_KEYS, normalize_activity_key

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
CHAT_SAVE_POOL_MINCONN = int(os.getenv("CHAT_SAVE_POOL_MINCONN", "1"))
CHAT_SAVE_POOL_MAXCONN = int(os.getenv("CHAT_SAVE_POOL_MAXCONN", "5"))
_chat_save_pool: pool.SimpleConnectionPool | None = None
_chat_save_pool_lock = threading.Lock()

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

DEMO_MISSION_IDS = [
    2, 12, 16, 25, 29, 38, 43, 51, 62,
    67, 71, 87, 96, 112, 153, 159, 168, 192,
]
_DEMO_MISSION_METADATA_COLUMNS = (
    "success_criteria",
    "strict_requirements",
    "target_metric",
    "target_value",
    "target_unit",
    "time_condition",
    "allowed_substitutes",
    "denied_substitutes",
)


def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def _get_chat_save_pool() -> pool.SimpleConnectionPool:
    global _chat_save_pool
    if _chat_save_pool is None:
        with _chat_save_pool_lock:
            if _chat_save_pool is None:
                _chat_save_pool = pool.SimpleConnectionPool(
                    CHAT_SAVE_POOL_MINCONN,
                    CHAT_SAVE_POOL_MAXCONN,
                    DATABASE_URL,
                )
                print(
                    "[DBTrace chat_save_pool] initialized "
                    f"min={CHAT_SAVE_POOL_MINCONN} max={CHAT_SAVE_POOL_MAXCONN}"
                )
    return _chat_save_pool


def _dbtrace(request_id: str | None, event: str, **fields) -> None:
    rid = request_id or "-"
    detail = " ".join(
        f"{key}={value}"
        for key, value in fields.items()
        if value is not None
    )
    suffix = f" {detail}" if detail else ""
    print(f"[DBTrace {rid}] {event}{suffix}")


def init_db():
    required_tables = (
        "session_profiles",
        "demo_mission",
        "pending_mission_suggestions",
        "student_app_state",
        "xp_history",
        "draw_runs",
        "attendance_log",
        "game_runs",
        "lesson_progress",
        "student_health_notes",
        "user_memories",
        "pending_actions",
        "mission_change_logs",
        "mission_reviews",
        "generated_missions",
        "mission_ui_actions",
        "weekly_share_prompts",
        "mission_correction_requests",
        "user_feedback",
    )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = ANY(%s)
                """,
                (list(required_tables),),
            )
            existing_tables = {row[0] for row in cur.fetchall()}
            missing_tables = sorted(set(required_tables) - existing_tables)
            if missing_tables:
                missing = ", ".join(missing_tables)
                raise RuntimeError(
                    "Database schema is missing runtime tables. "
                    "Run `psql \"$DATABASE_URL\" -f backend/migrations/003_runtime_schema.sql` "
                    f"before starting the server. Missing: {missing}"
                )

            # mission_id/is_active�??�기?? 구조 변경�? migrations/*.sql?�서 관리한??
            for idx, mission_id in enumerate(DEMO_MISSION_IDS, start=1):
                cur.execute(
                    """
                    INSERT INTO demo_mission (order_no, mission_id, is_active)
                    VALUES (%s, %s, TRUE)
                    ON CONFLICT (order_no) DO UPDATE
                        SET mission_id = EXCLUDED.mission_id,
                            is_active = TRUE
                    """,
                    (idx, mission_id),
                )
        conn.commit()


# ?�?� ?�생 본인 ?�인 (students ?�이�? ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

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


def _ensure_student_app_state(cur, student_id: int) -> None:
    cur.execute("""
        INSERT INTO student_app_state (student_id)
        VALUES (%s)
        ON CONFLICT (student_id) DO NOTHING
    """, (student_id,))


def delete_student_completely(student_id: int) -> bool:
    """?�퇴 처리: ?�생�??�생??참조?�는 모든 ?�이?��? ???�랜??��?�서 ??��.

    FK ?�존???�서�???��?�며, students ?�이 존재?��? ?�으�?False 반환.
    """
    if not student_id:
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM students WHERE student_id = %s", (student_id,))
            if cur.fetchone() is None:
                return False

            # chat_messages??chat_sessions.session_id�?참조?��?�?먼�? ??��.
            cur.execute(
                """
                DELETE FROM chat_messages
                WHERE session_id IN (
                    SELECT session_id FROM chat_sessions WHERE student_id = %s
                )
                """,
                (student_id,),
            )
            cur.execute("DELETE FROM chat_sessions WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM session_profiles WHERE student_id = %s", (student_id,))

            # xp_history??draw_runs(draw_id)�?참조?��?�?draw_runs보다 먼�?.
            cur.execute("DELETE FROM xp_history WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM draw_runs WHERE student_id = %s", (student_id,))

            cur.execute("DELETE FROM attendance_log WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM game_runs WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM lesson_progress WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM user_memories WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM pending_actions WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM pending_mission_suggestions WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM mission_correction_requests WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM user_feedback WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM mission_change_logs WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM mission_reviews WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM weekly_share_prompts WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM mission_ui_actions WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM generated_missions WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM mission_changes WHERE student_id = %s", (student_id,))
            cur.execute("SELECT to_regclass('public.mission_correction_requests')")
            if cur.fetchone()[0]:
                cur.execute(
                    """
                    DELETE FROM mission_correction_requests
                    WHERE checkin_id IN (
                        SELECT checkin_id FROM checkin_log WHERE student_id = %s
                    )
                    """,
                    (student_id,),
                )
            cur.execute("DELETE FROM checkin_log WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM student_daily_missions WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM student_app_state WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM student_health_notes WHERE student_id = %s", (student_id,))

            cur.execute("DELETE FROM students WHERE student_id = %s", (student_id,))
        conn.commit()

    return True


# ?�?� 채팅 ?�션 (chat_sessions ?�이�? ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

def _age_from_birth_date(birth_date: str | None) -> int | None:
    if not birth_date:
        return None
    try:
        born = datetime.strptime(birth_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    today = datetime.now(timezone(timedelta(hours=9))).date()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _normalize_gender(gender: str | None) -> str:
    value = (gender or "").strip().lower()
    if value in {"male", "m", "\ub0a8", "\ub0a8\uc790"}:
        return "\ub0a8"
    if value in {"female", "f", "\uc5ec", "\uc5ec\uc790"}:
        return "\uc5ec"
    return ""


def _ensure_student_optional_columns(cur) -> None:
    cur.execute("""
        ALTER TABLE students
        ADD COLUMN IF NOT EXISTS birth_date DATE,
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
    """)
    cur.execute("UPDATE students SET created_at = NOW() WHERE created_at IS NULL")
    cur.execute("UPDATE students SET updated_at = NOW() WHERE updated_at IS NULL")


def create_demo_student(student_name: str, phone_last4: str, birth_date: str | None = None, gender: str | None = None) -> dict:
    """
    Create a demo signup student in the existing students table.
    New demo signups are marked with student_note = '?�규 가??.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _ensure_student_optional_columns(cur)
            cur.execute(
                """
                SELECT *
                FROM students
                WHERE student_name = %s
                  AND is_active = TRUE
                """,
                (student_name,),
            )
            rows = cur.fetchall()

            for row in rows:
                phone = str(row.get("phone_number", "")).replace("-", "")
                if phone[-4:] == phone_last4:
                    clean_gender = _normalize_gender(gender)
                    age = _age_from_birth_date(birth_date)
                    if birth_date or clean_gender:
                        cur.execute(
                            """
                            UPDATE students
                               SET birth_date = COALESCE(%s::date, birth_date),
                                   age = COALESCE(%s, age),
                                   gender = COALESCE(NULLIF(%s, ''), gender),
                                   updated_at = NOW()
                             WHERE student_id = %s
                             RETURNING *
                            """,
                            (birth_date or None, age, clean_gender, row["student_id"]),
                        )
                        row = cur.fetchone()
                    _ensure_student_app_state(cur, row["student_id"])
                    conn.commit()
                    return dict(row)

            clean_gender = _normalize_gender(gender)
            age = _age_from_birth_date(birth_date)
            cur.execute("""
                INSERT INTO students (
                    student_name,
                    phone_number,
                    age,
                    gender,
                    birth_date,
                    location,
                    is_active,
                    student_note
                )
                VALUES (%s, %s, %s, %s, %s::date, '', TRUE, '?�규 가??)
                RETURNING *
            """, (student_name, phone_last4, age, clean_gender, birth_date or None))
            student = cur.fetchone()
            _ensure_student_app_state(cur, student["student_id"])

        conn.commit()

    return dict(student)


def update_student_optional_info(student_id: int, birth_date: str | None = None, gender: str | None = None) -> dict | None:
    clean_gender = _normalize_gender(gender)
    age = _age_from_birth_date(birth_date)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _ensure_student_optional_columns(cur)
            updates = ["updated_at = NOW()"]
            params: list = []
            if birth_date:
                updates.extend(["birth_date = %s::date", "age = %s"])
                params.extend([birth_date, age])
            if clean_gender:
                updates.append("gender = %s")
                params.append(clean_gender)
            params.append(student_id)
            cur.execute(
                f"""
                UPDATE students
                   SET {", ".join(updates)}
                 WHERE student_id = %s
                 RETURNING *
                """,
                params,
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


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


def get_latest_chat_session(student_id: int) -> int | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cs.session_id
                FROM chat_sessions cs
                LEFT JOIN chat_messages cm ON cm.session_id = cs.session_id
                WHERE cs.student_id = %s
                GROUP BY cs.session_id, cs.started_at
                ORDER BY COUNT(cm.message_id) DESC, MAX(cm.created_at) DESC NULLS LAST, cs.started_at DESC
                LIMIT 1
                """,
                (student_id,),
            )
            row = cur.fetchone()
    return row[0] if row else None


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


# ?�?� 채팅 메시지 (chat_messages ?�이�? ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

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


def save_chat_turn(
    session_id: str,
    user_content: str | None,
    assistant_content: str,
    detected_function: str | None = None,
    request_id: str | None = None,
) -> tuple[int, int]:
    """Save a user/assistant turn through the chat-save pool only.

    This intentionally does not change get_conn(), so the pool's blast radius is
    limited to the latency-sensitive final /chat/stream turn save.
    """
    total_started = time.perf_counter()
    pool_conn = _get_chat_save_pool()
    conn = None
    user_id = 0
    assistant_id = 0
    connect_ms = 0
    profile_ms = 0
    insert_user_ms = 0
    insert_assistant_ms = 0
    commit_ms = 0

    try:
        connect_started = time.perf_counter()
        conn = pool_conn.getconn()
        connect_ms = round((time.perf_counter() - connect_started) * 1000)
        conn.autocommit = False

        with conn.cursor() as cur:
            profile_started = time.perf_counter()
            cur.execute(
                "SELECT student_id, db_session_id FROM session_profiles WHERE session_id = %s",
                (session_id,),
            )
            profile = cur.fetchone()
            profile_ms = round((time.perf_counter() - profile_started) * 1000)
            if not profile:
                conn.rollback()
                _dbtrace(
                    request_id,
                    "save_chat_turn.missing_profile",
                    connect_ms=connect_ms,
                    profile_ms=profile_ms,
                    save_message_total_ms=round((time.perf_counter() - total_started) * 1000),
                )
                return 0, 0

            student_id, db_session_id = profile
            if user_content:
                insert_started = time.perf_counter()
                cur.execute(
                    """
                    INSERT INTO chat_messages
                        (session_id, student_id, speaker, message_text, detected_function)
                    VALUES (%s, %s, %s, %s, %s) RETURNING message_id
                    """,
                    (db_session_id, student_id, "student", user_content, detected_function),
                )
                user_id = cur.fetchone()[0]
                insert_user_ms = round((time.perf_counter() - insert_started) * 1000)

            insert_started = time.perf_counter()
            cur.execute(
                """
                INSERT INTO chat_messages
                    (session_id, student_id, speaker, message_text, detected_function)
                VALUES (%s, %s, %s, %s, %s) RETURNING message_id
                """,
                (db_session_id, student_id, "ai", assistant_content, None),
            )
            assistant_id = cur.fetchone()[0]
            insert_assistant_ms = round((time.perf_counter() - insert_started) * 1000)

        commit_started = time.perf_counter()
        conn.commit()
        commit_ms = round((time.perf_counter() - commit_started) * 1000)
        _dbtrace(
            request_id,
            "save_chat_turn.done",
            connect_ms=connect_ms,
            profile_ms=profile_ms,
            insert_user_ms=insert_user_ms,
            insert_assistant_ms=insert_assistant_ms,
            commit_ms=commit_ms,
            save_message_total_ms=round((time.perf_counter() - total_started) * 1000),
        )
        return user_id, assistant_id
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        _dbtrace(
            request_id,
            "save_chat_turn.error",
            error=f"{type(exc).__name__}: {exc}",
            connect_ms=connect_ms,
            profile_ms=profile_ms,
            insert_user_ms=insert_user_ms,
            insert_assistant_ms=insert_assistant_ms,
            commit_ms=commit_ms,
            save_message_total_ms=round((time.perf_counter() - total_started) * 1000),
        )
        return 0, 0
    finally:
        if conn is not None:
            try:
                pool_conn.putconn(conn)
            except Exception as exc:
                _dbtrace(request_id, "save_chat_turn.putconn_error", error=f"{type(exc).__name__}: {exc}")


def fetch_messages(session_id: str, limit: int | None = None) -> list[dict]:
    profile = fetch_profile(session_id)
    if not profile:
        return []
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if limit and limit > 0:
                cur.execute(
                    """
                    SELECT speaker, message_text, created_at
                    FROM (
                        SELECT message_id, speaker, message_text, created_at
                        FROM chat_messages
                        WHERE session_id = %s
                        ORDER BY message_id DESC
                        LIMIT %s
                    ) recent
                    ORDER BY message_id
                    """,
                    (profile["db_session_id"], limit),
                )
            else:
                cur.execute(
                    """
                    SELECT speaker, message_text, created_at
                    FROM chat_messages
                    WHERE session_id = %s
                    ORDER BY message_id
                    """,
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


# ?�?� ?�늘??미션 ?�동 배정 ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

def _kst_today() -> str:
    """?�국 ?�간(KST) 기�? ?�늘 ?�짜 반환."""
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")


def resolve_mission_query_date(target_date: str | None) -> str:
    today = datetime.strptime(_kst_today(), "%Y-%m-%d").date()

    if not target_date or target_date == "today":
        return today.strftime("%Y-%m-%d")
    if target_date == "yesterday":
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if target_date == "day_before_yesterday":
        return (today - timedelta(days=2)).strftime("%Y-%m-%d")

    try:
        return datetime.strptime(target_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return today.strftime("%Y-%m-%d")


def assign_daily_missions() -> int:
    """
    ?�늘(KST) 미션??배정 ?????�생?�게 ?�동 배정
    - 최근 7?�간 배정??미션?� ?�외
    - 7??기록 ?�으�??�덤 1�?배정
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
                      AND NOT EXISTS (
                          SELECT 1
                          FROM mission_changes mc
                          WHERE mc.student_id = s.student_id
                            AND mc.change_date >= %s::date - INTERVAL '7 days'
                            AND mc.change_date < %s::date
                            AND mc.old_mission_id = m.mission_id
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
            """, (today, today, today, today, today, today))
            assigned = cur.rowcount
        conn.commit()
    return assigned


# ?�?� ?�늘??미션 (student_daily_missions + missions ?�이�? ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

def assign_demo_mission_on_signup(student_id: int) -> dict | None:
    """
    Assign active demo missions in order to demo students.
    The sequence wraps after the last active demo_mission row.
    """
    today = _kst_today()

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(20260502)")

            cur.execute("""
                SELECT m.mission_id, m.mission_name, m.category, m.difficulty,
                       m.main_category, m.sub_category,
                       m.mission_location, m.reward_xp, m.mission_group,
                       m.mission_rule, m.mission_description, sdm.status
                FROM student_daily_missions sdm
                JOIN missions m ON sdm.mission_id = m.mission_id
                WHERE sdm.student_id = %s
                  AND sdm.assigned_date = %s::date
            """, (student_id, today))
            existing = cur.fetchone()
            if existing:
                conn.commit()
                return dict(existing)

            cur.execute("""
                SELECT COUNT(*) AS assigned_count
                FROM student_daily_missions sdm
                JOIN demo_mission dm ON sdm.mission_id = dm.mission_id
                WHERE sdm.assigned_date = %s::date
                  AND sdm.assigned_by = 'demo'
                  AND dm.is_active = TRUE
            """, (today,))
            assigned_count = cur.fetchone()["assigned_count"]

            cur.execute("""
                SELECT mission_id
                FROM demo_mission
                WHERE is_active = TRUE
                ORDER BY order_no
            """)
            pool = [row["mission_id"] for row in cur.fetchall()]

            if not pool:
                conn.commit()
                return None

            next_mission_id = pool[assigned_count % len(pool)]

            cur.execute("""
                INSERT INTO student_daily_missions (
                    student_id,
                    mission_id,
                    assigned_date,
                    status,
                    assigned_by
                )
                SELECT %s, %s, %s::date, 'assigned', 'demo'
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM student_daily_missions
                    WHERE student_id = %s
                      AND assigned_date = %s::date
                )
            """, (student_id, next_mission_id, today, student_id, today))

            cur.execute("""
                SELECT m.mission_id, m.mission_name, m.category, m.difficulty,
                       m.main_category, m.sub_category,
                       m.mission_location, m.reward_xp, m.mission_group,
                       m.mission_rule, m.mission_description, sdm.status
                FROM student_daily_missions sdm
                JOIN missions m ON sdm.mission_id = m.mission_id
                WHERE sdm.student_id = %s
                  AND sdm.assigned_date = %s::date
            """, (student_id, today))
            mission = cur.fetchone()

        conn.commit()

    return dict(mission) if mission else None


def get_student_mission_db(student_id: int, today: str | None = None) -> dict | None:
    if today is None:
        today = _kst_today()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT m.mission_id, m.mission_name, m.category, m.difficulty,
                       m.main_category, m.sub_category,
                       m.mission_location, m.reward_xp, m.mission_group,
                       m.mission_rule, m.mission_description, m.activity_key, sdm.status,
                       dm.success_criteria, dm.strict_requirements,
                       dm.target_metric, dm.target_value, dm.target_unit,
                       dm.time_condition, dm.allowed_substitutes, dm.denied_substitutes
                FROM student_daily_missions sdm
                JOIN missions m ON sdm.mission_id = m.mission_id
                LEFT JOIN demo_mission dm ON dm.mission_id = m.mission_id
                WHERE sdm.student_id = %s AND sdm.assigned_date = %s
                """,
                (student_id, today),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def normalize_mission_text(text: str) -> str:
    """미션�?비교???�규?? 공백 ?�거 + ?�문?�화."""
    return (text or "").replace(" ", "").strip().lower()


def find_mission_by_user_text(user_text: str) -> dict | None:
    """
    ?�용??발화 ?�에 missions.mission_name???�확???�함?�어 ?�으�??�당 미션 반환.

    ??
    user_text = "채소 반찬 먹기�?미션 바꿔�?
    mission_name = "채소 반찬 먹기"
    ??공백 ?�거 ??"채소반찬먹기"가 ?�용??발화???�함?�면 ?�확 매칭?�로 ?�단
    """
    normalized_text = normalize_mission_text(user_text)
    if not normalized_text:
        return None

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT mission_id, mission_name, mission_rule
                FROM missions
                WHERE is_active = TRUE
                ORDER BY mission_id
            """)
            rows = cur.fetchall()

    for row in rows:
        mission_name_norm = normalize_mission_text(row["mission_name"])
        if mission_name_norm and mission_name_norm in normalized_text:
            return dict(row)

    return None


def find_similar_mission_by_user_text(user_text: str) -> dict | None:
    """
    ?�용??발화?�서 2글???�상 ?�큰??뽑아 mission_name�?부�?매칭?�다.
    ?�확 매칭???�을 ???�사 미션 ?�안?�으�??�용?�다.
    """
    cleaned = (user_text or "").strip()
    if not cleaned:
        return None

    remove_words = [
        "미션",
        "바꿔",
        "바꿔줄래",
        "변경해",
        "변경",
        "바꾸고싶어",
        "그럼",
        "로",
        "으로",
        "좀",
        "해줘",
        "하는",
        "거야",
    ]

    keyword_text = cleaned
    for word in remove_words:
        keyword_text = keyword_text.replace(word, " ")

    tokens = [
        token.strip()
        for token in keyword_text.split()
        if len(token.strip()) >= 2
    ]

    if not tokens:
        return None

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for token in tokens:
                cur.execute("""
                    SELECT mission_id, mission_name, mission_rule
                    FROM missions
                    WHERE is_active = TRUE
                      AND mission_name ILIKE %s
                    ORDER BY mission_id
                    LIMIT 1
                """, (f"%{token}%",))
                row = cur.fetchone()
                if row:
                    return dict(row)

    return None


def save_pending_mission_suggestion(
    student_id: int,
    suggested_mission_id: int,
    source_text: str | None = None,
) -> None:
    """
    기존 pending ?�안?� 취소?�고 ???�안???�?�한??
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE pending_mission_suggestions
                SET status = 'cancelled',
                    resolved_at = NOW()
                WHERE student_id = %s
                  AND status = 'pending'
            """, (student_id,))

            cur.execute("""
                INSERT INTO pending_mission_suggestions (
                    student_id,
                    suggested_mission_id,
                    source_text,
                    status
                )
                VALUES (%s, %s, %s, 'pending')
            """, (student_id, suggested_mission_id, source_text))

        conn.commit()


def get_pending_mission_suggestion(student_id: int) -> dict | None:
    today = _kst_today()

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    pms.suggestion_id,
                    pms.student_id,
                    pms.suggested_mission_id,
                    m.mission_name,
                    m.mission_rule,
                    pms.source_text,
                    pms.created_at
                FROM pending_mission_suggestions pms
                JOIN missions m ON m.mission_id = pms.suggested_mission_id
                WHERE pms.student_id = %s
                  AND pms.status = 'pending'
                  AND (pms.created_at AT TIME ZONE 'Asia/Seoul')::date = %s::date
                ORDER BY pms.created_at DESC
                LIMIT 1
            """, (student_id, today))
            row = cur.fetchone()

    return dict(row) if row else None


def resolve_pending_mission_suggestion(suggestion_id: int, status: str = "accepted") -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE pending_mission_suggestions
                SET status = %s,
                    resolved_at = NOW()
                WHERE suggestion_id = %s
            """, (status, suggestion_id))
        conn.commit()


def has_checkin_today(student_id: int) -> bool:
    """
    ?�늘(KST) 미션 결과�??��? ?�출?�는지 ?�인.
    checkin_log??submit_mission_result 기록???�으�?True.
    """
    today = _kst_today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1
                FROM checkin_log
                WHERE student_id = %s
                  AND checkin_date = %s::date
                  AND function_called = 'submit_mission_result'
                  AND mission_result IS DISTINCT FROM 'cancelled'
                LIMIT 1
            """, (student_id, today))
            row = cur.fetchone()
    return row is not None


# ?�?� ?�생 ?�보 조회 (students ?�이�? ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

def get_success_summary(student_id: int) -> dict:
    today = _kst_today()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT ON (checkin_date)
                       checkin_date::text AS checkin_date,
                       mission_result
                FROM checkin_log
                WHERE student_id = %s
                  AND function_called = 'submit_mission_result'
                  AND mission_result IS DISTINCT FROM 'cancelled'
                ORDER BY checkin_date DESC, created_at DESC
            """, (student_id,))
            rows = [dict(r) for r in cur.fetchall()]

    success_dates = {
        r["checkin_date"]
        for r in rows
        if r.get("mission_result") in ("success", "completed")
    }

    today_date = datetime.strptime(today, "%Y-%m-%d").date()
    cursor = today_date if today in success_dates else today_date - timedelta(days=1)
    streak = 0

    while cursor.strftime("%Y-%m-%d") in success_dates:
        streak += 1
        cursor -= timedelta(days=1)

    return {
        "success_dates": sorted(success_dates),
        "success_count": len(success_dates),
        "streak_days": streak,
    }


def _previous_week_range(today: date | None = None) -> tuple[date, date]:
    today_date = today or datetime.strptime(_kst_today(), "%Y-%m-%d").date()
    current_week_start = today_date - timedelta(days=today_date.weekday())
    week_start = current_week_start - timedelta(days=7)
    week_end = current_week_start - timedelta(days=1)
    return week_start, week_end


def get_weekly_share_prompt(student_id: int) -> dict:
    if not student_id:
        raise ValueError("student_id is required")

    week_start, week_end = _previous_week_range()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, prompt_shown_at, dismissed_at, shared_at
                FROM weekly_share_prompts
                WHERE student_id = %s
                  AND week_start = %s
                LIMIT 1
            """, (student_id, week_start))
            existing_prompt = cur.fetchone()

            cur.execute("""
                SELECT DISTINCT ON (cl.checkin_date)
                       cl.checkin_date::text AS checkin_date,
                       cl.mission_result,
                       cl.mission_id,
                       m.mission_name
                FROM checkin_log cl
                LEFT JOIN missions m ON m.mission_id = cl.mission_id
                WHERE cl.student_id = %s
                  AND cl.function_called = 'submit_mission_result'
                  AND cl.checkin_date BETWEEN %s AND %s
                ORDER BY cl.checkin_date, cl.created_at DESC
            """, (student_id, week_start, week_end))
            mission_rows = [dict(row) for row in cur.fetchall()]

            success_statuses = {"success", "completed"}
            fail_statuses = {"fail", "failure"}
            success_count = sum(1 for row in mission_rows if row.get("mission_result") in success_statuses)
            fail_count = sum(1 for row in mission_rows if row.get("mission_result") in fail_statuses)
            total_count = len(mission_rows)

            should_show = total_count > 0 and existing_prompt is None
            prompt_id = existing_prompt["id"] if existing_prompt else None
            if should_show:
                cur.execute("""
                    INSERT INTO weekly_share_prompts (student_id, week_start, week_end)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (student_id, week_start) DO NOTHING
                    RETURNING id
                """, (student_id, week_start, week_end))
                inserted = cur.fetchone()
                prompt_id = inserted["id"] if inserted else None

        conn.commit()

    missions = [
        {
            "date": row.get("checkin_date"),
            "mission_id": row.get("mission_id"),
            "mission_name": row.get("mission_name") or "미션",
            "result": row.get("mission_result"),
        }
        for row in mission_rows
    ]
    return {
        "should_show": should_show,
        "prompt_id": prompt_id,
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": week_end.strftime("%Y-%m-%d"),
        "summary": {
            "total_count": total_count,
            "success_count": success_count,
            "fail_count": fail_count,
            "missions": missions,
        },
    }


def mark_weekly_share_prompt(student_id: int, week_start: str, action: str) -> dict:
    if action not in {"dismissed", "shared"}:
        raise ValueError("action must be dismissed or shared")
    if not student_id:
        raise ValueError("student_id is required")

    try:
        week_start_date = datetime.strptime(week_start, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError("week_start must be YYYY-MM-DD")

    week_end_date = week_start_date + timedelta(days=6)
    timestamp_column = "shared_at" if action == "shared" else "dismissed_at"
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                INSERT INTO weekly_share_prompts (
                    student_id, week_start, week_end, {timestamp_column}, updated_at
                )
                VALUES (%s, %s, %s, NOW(), NOW())
                ON CONFLICT (student_id, week_start)
                DO UPDATE SET
                    {timestamp_column} = NOW(),
                    updated_at = NOW()
                RETURNING id, student_id,
                          week_start::text AS week_start,
                          week_end::text AS week_end,
                          prompt_shown_at, dismissed_at, shared_at
            """, (student_id, week_start_date, week_end_date))
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def get_app_state(student_id: int) -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _ensure_student_app_state(cur, student_id)
            cur.execute("""
                SELECT student_id, level, current_xp, ticket_count, heart_count
                FROM student_app_state
                WHERE student_id = %s
            """, (student_id,))
            row = cur.fetchone()
        conn.commit()
    return dict(row)


# ?�?� ?�벨/XP 계산 ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�
# ?�적 XP ?�계�? key = �??�벨???�달?�기 ?�해 ?�요???�적 XP
# ?�론??LEVEL_THRESHOLDS?� ?�확???�치?�야 ??
_LEVEL_THRESHOLDS = {2: 5, 3: 17, 4: 37, 5: 70, 6: 150}
_MAX_LEVEL = 5
_MAX_HEARTS = 5
_DIFFICULTY_XP_FALLBACK = {"easy": 5, "medium": 10, "hard": 12}
_MISSION_TICKET_REWARD = 1


def adjust_heart_count(student_id: int, delta: int) -> dict:
    """
    Atomically adjust a student's hearts and return the latest app_state.
    Negative deltas require enough hearts; positive deltas are capped.
    """
    if delta == 0:
        return get_app_state(student_id)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO student_app_state (student_id)
                VALUES (%s)
                ON CONFLICT (student_id) DO NOTHING
            """, (student_id,))
            cur.execute("""
                SELECT level, current_xp, ticket_count, heart_count
                FROM student_app_state
                WHERE student_id = %s
                FOR UPDATE
            """, (student_id,))
            current = cur.fetchone()
            if not current:
                raise ValueError("missing_app_state")

            next_heart = current["heart_count"] + delta
            if next_heart < 0:
                raise ValueError("no_heart")
            next_heart = min(_MAX_HEARTS, next_heart)

            cur.execute("""
                UPDATE student_app_state
                SET heart_count = %s,
                    updated_at = NOW()
                WHERE student_id = %s
                RETURNING student_id, level, current_xp, ticket_count, heart_count
            """, (next_heart, student_id))
            updated = cur.fetchone()
        conn.commit()
    return dict(updated)


def _recompute_level(current_xp: int) -> int:
    lv = 1
    while lv < _MAX_LEVEL and current_xp >= _LEVEL_THRESHOLDS.get(lv + 1, 10**9):
        lv += 1
    return lv


def award_mission_xp(student_id: int, mission_id: int) -> dict:
    """
    미션 ?�공 보상 지�? ?�일 ?�랜??��:
      1) 미션??reward_xp 조회 (?�으�?difficulty 기반 fallback)
      2) student_app_state UPSERT ??current_xp += gain, level ?�계?? ticket_count += 1
      3) xp_history INSERT ??source_type='mission_success', mission_id=mission_id

    Returns dict:
      { xp_gain, ticket_gain, level_before, level_after, leveled_up, app_state }
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT reward_xp, difficulty FROM missions WHERE mission_id = %s",
                (mission_id,),
            )
            mission_row = cur.fetchone()
            if not mission_row:
                raise ValueError(f"mission {mission_id} not found")

            xp_gain = mission_row.get("reward_xp")
            if not xp_gain or xp_gain <= 0:
                difficulty = (mission_row.get("difficulty") or "easy").lower()
                xp_gain = _DIFFICULTY_XP_FALLBACK.get(difficulty, _DIFFICULTY_XP_FALLBACK["easy"])

            cur.execute("""
                INSERT INTO student_app_state (student_id)
                VALUES (%s)
                ON CONFLICT (student_id) DO NOTHING
            """, (student_id,))
            cur.execute("""
                SELECT level, current_xp, ticket_count, heart_count
                FROM student_app_state
                WHERE student_id = %s
                FOR UPDATE
            """, (student_id,))
            current = cur.fetchone()

            level_before = current["level"]
            new_xp = current["current_xp"] + xp_gain
            new_level = _recompute_level(new_xp)
            new_ticket = current["ticket_count"] + _MISSION_TICKET_REWARD

            cur.execute("""
                UPDATE student_app_state
                   SET level = %s,
                       current_xp = %s,
                       ticket_count = %s,
                       updated_at = NOW()
                 WHERE student_id = %s
                RETURNING student_id, level, current_xp, ticket_count, heart_count
            """, (new_level, new_xp, new_ticket, student_id))
            updated = cur.fetchone()

            cur.execute("""
                INSERT INTO xp_history (student_id, xp_amount, source_type, mission_id)
                VALUES (%s, %s, 'mission_success', %s)
            """, (student_id, xp_gain, mission_id))

        conn.commit()

    return {
        "xp_gain": xp_gain,
        "ticket_gain": _MISSION_TICKET_REWARD,
        "level_before": level_before,
        "level_after": updated["level"],
        "leveled_up": updated["level"] > level_before,
        "app_state": dict(updated),
    }


def _roll_draw_reward(is_first_of_day: bool) -> dict:
    """가�?보상 분포 (?�론??rollReward?� ?�일):
       - �?뽑기: ?�트 1-2 ?�정
       - ?�후: 40% ?�트(1-2), 40% XP(3-5), 20% ?�트+XP
    """
    if is_first_of_day:
        return {"type": "heart", "heart": random.randint(1, 2), "exp": 0}
    r = random.random()
    if r < 0.4:
        return {"type": "heart", "heart": random.randint(1, 2), "exp": 0}
    if r < 0.8:
        return {"type": "exp", "heart": 0, "exp": random.randint(3, 5)}
    return {"type": "both", "heart": random.randint(1, 2), "exp": random.randint(3, 5)}


def claim_draw_reward(student_id: int) -> dict:
    """
    가�?????처리. ?�일 ?�랜??��:
      1) student_app_state FOR UPDATE ???�켓 ?? 검�?
      2) ?�늘(KST) draw_runs 조회 ??first_of_day ?�정
      3) 보상 굴림 (?�버 ?�속)
      4) app_state ?�데?�트 ??ticket -1, heart += gain (cap), xp += gain (level ?�계??
      5) draw_runs INSERT ??draw_id
      6) xp_gain > 0 ?�면 xp_history INSERT (source_type='draw_reward', draw_id=draw_id)

    Raises ValueError("no_ticket") if ticket_count == 0.

    Returns dict:
      { reward, app_state, leveled_up, level_after, xp_gain, heart_gain, ticket_gain, first_of_day }
    """
    today_kst = _kst_today()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO student_app_state (student_id)
                VALUES (%s)
                ON CONFLICT (student_id) DO NOTHING
            """, (student_id,))
            cur.execute("""
                SELECT level, current_xp, ticket_count, heart_count
                FROM student_app_state
                WHERE student_id = %s
                FOR UPDATE
            """, (student_id,))
            current = cur.fetchone()
            if current["ticket_count"] <= 0:
                raise ValueError("no_ticket")

            cur.execute("""
                SELECT COUNT(*) AS n
                FROM draw_runs
                WHERE student_id = %s
                  AND (created_at AT TIME ZONE 'Asia/Seoul')::date = %s::date
            """, (student_id, today_kst))
            today_count = cur.fetchone()["n"]
            first_of_day = today_count == 0

            reward = _roll_draw_reward(first_of_day)
            heart_gain = reward["heart"]
            xp_gain = reward["exp"]

            level_before = current["level"]
            new_xp = current["current_xp"] + xp_gain
            new_level = _recompute_level(new_xp)
            new_ticket = current["ticket_count"] - 1
            new_heart = min(_MAX_HEARTS, current["heart_count"] + heart_gain)

            cur.execute("""
                UPDATE student_app_state
                   SET level = %s,
                       current_xp = %s,
                       ticket_count = %s,
                       heart_count = %s,
                       updated_at = NOW()
                 WHERE student_id = %s
                RETURNING student_id, level, current_xp, ticket_count, heart_count
            """, (new_level, new_xp, new_ticket, new_heart, student_id))
            updated = cur.fetchone()

            cur.execute("""
                INSERT INTO draw_runs (student_id, reward_type, heart_gain, xp_gain)
                VALUES (%s, %s, %s, %s)
                RETURNING draw_id
            """, (student_id, reward["type"], heart_gain, xp_gain))
            draw_id = cur.fetchone()["draw_id"]

            if xp_gain > 0:
                cur.execute("""
                    INSERT INTO xp_history (student_id, xp_amount, source_type, draw_id)
                    VALUES (%s, %s, 'draw_reward', %s)
                """, (student_id, xp_gain, draw_id))

        conn.commit()

    return {
        "reward": reward,
        "app_state": dict(updated),
        "leveled_up": updated["level"] > level_before,
        "level_after": updated["level"],
        "xp_gain": xp_gain,
        "heart_gain": heart_gain,
        "ticket_gain": -1,
        "first_of_day": first_of_day,
    }


_ATTENDANCE_TICKET_REWARD = 1


def claim_attendance(student_id: int) -> dict:
    """
    ?�늘(KST) �?출석?�면 ticket +1. ??번째 ?�후??no-op.

    attendance_log??(student_id, attendance_date) PRIMARY KEY�??�루 1??보장.

    Returns dict:
      { first_check_in: bool, ticket_awarded: int, app_state: {...} }
    """
    today_kst = _kst_today()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO student_app_state (student_id)
                VALUES (%s)
                ON CONFLICT (student_id) DO NOTHING
            """, (student_id,))

            cur.execute("""
                INSERT INTO attendance_log (student_id, attendance_date, ticket_awarded)
                VALUES (%s, %s, %s)
                ON CONFLICT (student_id, attendance_date) DO NOTHING
                RETURNING student_id
            """, (student_id, today_kst, _ATTENDANCE_TICKET_REWARD))
            inserted = cur.fetchone()
            first_check_in = inserted is not None

            if first_check_in:
                cur.execute("""
                    UPDATE student_app_state
                       SET ticket_count = ticket_count + %s,
                           updated_at = NOW()
                     WHERE student_id = %s
                    RETURNING student_id, level, current_xp, ticket_count, heart_count
                """, (_ATTENDANCE_TICKET_REWARD, student_id))
            else:
                cur.execute("""
                    SELECT student_id, level, current_xp, ticket_count, heart_count
                    FROM student_app_state
                    WHERE student_id = %s
                """, (student_id,))
            current = cur.fetchone()

        conn.commit()

    return {
        "first_check_in": first_check_in,
        "ticket_awarded": _ATTENDANCE_TICKET_REWARD if first_check_in else 0,
        "app_state": dict(current),
    }


# ?�?� 경험�???�� ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

_KST = timezone(timedelta(hours=9))


def _period_start_utc(period: str) -> datetime | None:
    """
    'week' = ?�번 �??�요??00:00 KST
    'month' = ?�번 ??1??00:00 KST
    'all' = None (?�터 ?�음)
    UTC�?변?�해??반환.
    """
    if period == "all":
        return None
    now_kst = datetime.now(_KST)
    if period == "month":
        start_kst = now_kst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # default = week
        days_since_monday = now_kst.weekday()  # Mon=0
        start_kst = (now_kst - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    return start_kst.astimezone(timezone.utc)


def get_xp_ranking(period: str = "week", limit: int = 100) -> list[dict]:
    """
    기간 ??xp_history ?�계 기�? ??��.
    student_app_state??모든 ?�생??LEFT JOIN?�서, 기간??XP �?받�? ?�생??0?�로 ?�함.
    ?�률?� level DESC, current_xp DESC�?�?
    Returns: [{rank, student_id, student_name, level, period_xp}, ...]
    """
    period_start = _period_start_utc(period)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    sas.student_id,
                    s.student_name,
                    sas.level,
                    sas.current_xp,
                    COALESCE(SUM(xh.xp_amount), 0)::int AS period_xp
                FROM student_app_state sas
                JOIN students s ON s.student_id = sas.student_id
                LEFT JOIN xp_history xh
                       ON xh.student_id = sas.student_id
                      AND xh.created_at >= %s
                WHERE s.is_active = TRUE
                GROUP BY sas.student_id, s.student_name, sas.level, sas.current_xp
                ORDER BY period_xp DESC, sas.level DESC, sas.current_xp DESC, sas.student_id ASC
                LIMIT %s
            """, (period_start, limit))
            rows = cur.fetchall()

    return [
        {
            "rank": i + 1,
            "student_id": row["student_id"],
            "student_name": row["student_name"],
            "level": row["level"],
            "period_xp": row["period_xp"],
        }
        for i, row in enumerate(rows)
    ]


# ?�?� 게임 기록 / ??�� ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

def record_game_run(
    student_id: int,
    game_type: str,
    score: int,
    duration_sec: int = 0,
) -> dict:
    """게임 ????기록. Returns inserted row."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO game_runs (student_id, game_type, score, duration_sec)
                VALUES (%s, %s, %s, %s)
                RETURNING run_id, student_id, game_type, score, duration_sec, played_at
            """, (student_id, game_type, score, duration_sec))
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def get_game_ranking(
    period: str = "week",
    limit: int = 100,
    game_type: str | None = None,
) -> list[dict]:
    """
    기간 ??game_runs MAX(score) 기�? ??��.
    student_app_state??모든 ?�생??LEFT JOIN ??미플?�이??best_score=0, plays=0?�로 ?�함.
    ?�률?� plays DESC, level DESC, student_id ASC�?�?
    Returns: [{rank, student_id, student_name, level, best_score, plays}, ...]
    """
    period_start = _period_start_utc(period)
    where_clauses = []
    params: list = []
    if period_start is not None:
        where_clauses.append("gr.played_at >= %s")
        params.append(period_start)
    if game_type:
        where_clauses.append("gr.game_type = %s")
        params.append(game_type)
    join_filter = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT
                    sas.student_id,
                    s.student_name,
                    sas.level,
                    COALESCE(MAX(gr.score), 0)::int AS best_score,
                    COUNT(gr.run_id)::int AS plays
                FROM student_app_state sas
                JOIN students s ON s.student_id = sas.student_id
                LEFT JOIN game_runs gr
                       ON gr.student_id = sas.student_id
                       {join_filter}
                WHERE s.is_active = TRUE
                GROUP BY sas.student_id, s.student_name, sas.level
                ORDER BY best_score DESC, plays DESC, sas.level DESC, sas.student_id ASC
                LIMIT %s
            """, (*params, limit))
            rows = cur.fetchall()

    return [
        {
            "rank": i + 1,
            "student_id": row["student_id"],
            "student_name": row["student_name"],
            "level": row["level"],
            "best_score": row["best_score"],
            "plays": row["plays"],
        }
        for i, row in enumerate(rows)
    ]


# ?�?� ?�습 진행???�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

_QUIZ_TICKET_REWARD = 1


def get_lesson_progress(student_id: int) -> list[dict]:
    """?�생??모든 lesson 진행?? ?�으�?�?리스??"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT student_id, lesson_id, current_step, edu_done, quiz_done,
                       quiz_score, completed_at, updated_at
                FROM lesson_progress
                WHERE student_id = %s
                ORDER BY updated_at DESC
            """, (student_id,))
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def upsert_lesson_progress(
    student_id: int,
    lesson_id: str,
    current_step: int | None = None,
    edu_done: bool | None = None,
    quiz_done: bool | None = None,
) -> dict:
    """
    부�??�데?�트. None?� 기존 �??��?. (student_id, lesson_id)??row ?�으�??�로 만듦.
    quiz_done??처음 True가 ????completed_at ?�동 ?�팅.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO lesson_progress (student_id, lesson_id)
                VALUES (%s, %s)
                ON CONFLICT (student_id, lesson_id) DO NOTHING
            """, (student_id, lesson_id))
            cur.execute("""
                SELECT current_step, edu_done, quiz_done
                FROM lesson_progress
                WHERE student_id = %s AND lesson_id = %s
                FOR UPDATE
            """, (student_id, lesson_id))
            curr = cur.fetchone()

            new_step = current_step if current_step is not None else curr["current_step"]
            new_edu = edu_done if edu_done is not None else curr["edu_done"]
            new_quiz = quiz_done if quiz_done is not None else curr["quiz_done"]
            quiz_just_completed = new_quiz and not curr["quiz_done"]

            cur.execute("""
                UPDATE lesson_progress
                   SET current_step = %s,
                       edu_done = %s,
                       quiz_done = %s,
                       completed_at = CASE WHEN %s THEN NOW() ELSE completed_at END,
                       updated_at = NOW()
                 WHERE student_id = %s AND lesson_id = %s
                RETURNING student_id, lesson_id, current_step, edu_done, quiz_done,
                          quiz_score, completed_at, updated_at
            """, (new_step, new_edu, new_quiz, quiz_just_completed, student_id, lesson_id))
            updated = cur.fetchone()
        conn.commit()
    return dict(updated)


def complete_lesson_quiz(
    student_id: int,
    lesson_id: str,
    quiz_score: int | None = None,
) -> dict:
    """
    ?�즈 ?�료 처리. �??�료�?ticket +1 지�?(idempotent ????번째부?�는 ?�태�?갱신).

    Returns:
      { progress, app_state, first_completion: bool, ticket_awarded: int }
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO lesson_progress (student_id, lesson_id)
                VALUES (%s, %s)
                ON CONFLICT (student_id, lesson_id) DO NOTHING
            """, (student_id, lesson_id))
            cur.execute("""
                SELECT quiz_done
                FROM lesson_progress
                WHERE student_id = %s AND lesson_id = %s
                FOR UPDATE
            """, (student_id, lesson_id))
            curr = cur.fetchone()
            first_completion = not curr["quiz_done"]

            cur.execute("""
                UPDATE lesson_progress
                   SET quiz_done = TRUE,
                       quiz_score = COALESCE(%s, quiz_score),
                       completed_at = CASE WHEN %s THEN NOW() ELSE completed_at END,
                       updated_at = NOW()
                 WHERE student_id = %s AND lesson_id = %s
                RETURNING student_id, lesson_id, current_step, edu_done, quiz_done,
                          quiz_score, completed_at, updated_at
            """, (quiz_score, first_completion, student_id, lesson_id))
            progress = cur.fetchone()

            cur.execute("""
                INSERT INTO student_app_state (student_id)
                VALUES (%s)
                ON CONFLICT (student_id) DO NOTHING
            """, (student_id,))

            if first_completion:
                cur.execute("""
                    UPDATE student_app_state
                       SET ticket_count = ticket_count + %s,
                           updated_at = NOW()
                     WHERE student_id = %s
                    RETURNING student_id, level, current_xp, ticket_count, heart_count
                """, (_QUIZ_TICKET_REWARD, student_id))
            else:
                cur.execute("""
                    SELECT student_id, level, current_xp, ticket_count, heart_count
                    FROM student_app_state
                    WHERE student_id = %s
                """, (student_id,))
            app_state = cur.fetchone()

        conn.commit()

    return {
        "progress": dict(progress),
        "app_state": dict(app_state),
        "first_completion": first_completion,
        "ticket_awarded": _QUIZ_TICKET_REWARD if first_completion else 0,
    }


def get_health_note(student_id: int) -> dict | None:
    """?�생 건강?�트 최신 �? ?�으�?None."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT student_id, allergens, caution_foods, created_at, updated_at
                FROM student_health_notes
                WHERE student_id = %s
            """, (student_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def upsert_health_note(
    student_id: int,
    allergens: list[str] | None = None,
    caution_foods: list[str] | None = None,
) -> dict:
    """?�생 건강?�트�?student_id 기�??�로 1개만 ?�??"""
    clean_allergens = [str(x).strip() for x in (allergens or []) if str(x).strip()]
    clean_caution_foods = [str(x).strip() for x in (caution_foods or []) if str(x).strip()]
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO student_health_notes (student_id, allergens, caution_foods)
                VALUES (%s, %s, %s)
                ON CONFLICT (student_id) DO UPDATE
                   SET allergens = EXCLUDED.allergens,
                       caution_foods = EXCLUDED.caution_foods,
                       updated_at = NOW()
                RETURNING student_id, allergens, caution_foods, created_at, updated_at
            """, (student_id, Json(clean_allergens), Json(clean_caution_foods)))
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def delete_health_note(student_id: int) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM student_health_notes WHERE student_id = %s", (student_id,))
            deleted = cur.rowcount
        conn.commit()
    return deleted


def get_student_info_db(student_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM students WHERE student_id = %s",
                (student_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


# ?�?� 미션 결과 ?�??(checkin_log ?�이�? ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

def save_mission_result(
    student_id: int,
    mission_id: int,
    status: str,
    result_reason: str | None = None,
    detected_function: str = "submit_mission_result",
) -> int | None:
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
                ON CONFLICT (student_id, checkin_date)
                    WHERE function_called = 'submit_mission_result'
                      AND mission_result IS DISTINCT FROM 'cancelled'
                DO NOTHING
                RETURNING checkin_id
                """,
                (student_id, mission_id, today, status,
                 result_reason, detected_function),
            )
            row = cur.fetchone()
            row_id = row[0] if row else None
            if row_id is not None:
                cur.execute(
                    """
                    UPDATE student_daily_missions
                    SET status = %s, updated_at = NOW()
                    WHERE student_id = %s
                      AND mission_id = %s
                      AND assigned_date = %s::date
                    """,
                    (status, student_id, mission_id, today),
                )
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


def _resolve_target_date(target_date: str | None, today_date: date) -> date | None:
    if not target_date:
        return None
    value = target_date.strip()
    if value == "today":
        return today_date
    if value == "yesterday":
        return today_date - timedelta(days=1)
    if value == "day_before_yesterday":
        return today_date - timedelta(days=2)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_target_month(target_month: str | None, today_date: date) -> date | None:
    if not target_month:
        return None
    value = target_month.strip()
    for fmt in ("%Y-%m", "%m"):
        try:
            parsed = datetime.strptime(value, fmt)
            year = parsed.year if fmt == "%Y-%m" else today_date.year
            return date(year, parsed.month, 1)
        except ValueError:
            continue
    return None


def get_user_history_db(
    student_id: int,
    query_type: str,
    target_period: str | None = None,
    target_date: str | None = None,
    target_month: str | None = None,
) -> dict:
    """
    query_type: 'daily_summary' | 'weekly_summary' | 'monthly_summary'
    target_period: 'this_week' | 'last_week' | 'this_month' | 'last_month'
    target_date: 'today' | 'yesterday' | 'day_before_yesterday' | 'YYYY-MM-DD'
    target_month: 'MM' | 'YYYY-MM'
    """
    today_str = _kst_today()
    today_date = datetime.strptime(today_str, "%Y-%m-%d").date()

    def empty(label: str, clarification_message: str = "") -> dict:
        return {
            "period_label": label,
            "records": [],
            "fallback": False,
            "fallback_label": "",
            "need_clarification": bool(clarification_message),
            "clarification_message": clarification_message,
        }

    if query_type == "daily_summary":
        resolved_date = _resolve_target_date(target_date, today_date)
        if not resolved_date:
            return empty("?�루 기록", "?�느 ??기록??보고 ?��?지 ?�늘, ?�제, 그�?께처???�시 물어봐줘.")
        period_start = resolved_date
        period_end = resolved_date + timedelta(days=1)
        if resolved_date == today_date:
            period_label = f"?�늘 ({resolved_date.strftime('%m/%d')})"
        elif resolved_date == today_date - timedelta(days=1):
            period_label = f"?�제 ({resolved_date.strftime('%m/%d')})"
        elif resolved_date == today_date - timedelta(days=2):
            period_label = f"그�?�?({resolved_date.strftime('%m/%d')})"
        else:
            period_label = resolved_date.strftime("%Y-%m-%d")
        prev_start = prev_end = None
        fallback_label = ""
    elif query_type == "weekly_summary":
        this_week_start = today_date - timedelta(days=today_date.weekday())
        if target_period == "last_week":
            period_start = this_week_start - timedelta(days=7)
            period_end = this_week_start
            period_label = (
                f"지?�주 ({period_start.strftime('%m/%d')}~"
                f"{(period_end - timedelta(days=1)).strftime('%m/%d')})"
            )
            prev_start = prev_end = None
            fallback_label = ""
        else:
            period_start = this_week_start
            period_end = today_date + timedelta(days=1)
            period_label = f"?�번 �?({period_start.strftime('%m/%d')}~{today_date.strftime('%m/%d')})"
            prev_start = period_start - timedelta(days=7)
            prev_end = period_start
            fallback_label = "지?�주"
    elif query_type == "monthly_summary":
        if target_month:
            period_start = _resolve_target_month(target_month, today_date)
            if not period_start:
                return empty("?�간 기록", "�???기록??보고 ?��?지 ?�시 물어봐줘.")
            period_end = date(period_start.year + (period_start.month // 12), (period_start.month % 12) + 1, 1)
            period_label = period_start.strftime("%Y년 %m월")
            prev_start = prev_end = None
            fallback_label = ""
        elif target_period == "last_month":
            this_month_start = today_date.replace(day=1)
            last_month_end = this_month_start - timedelta(days=1)
            period_start = last_month_end.replace(day=1)
            period_end = this_month_start
            period_label = f"지?�달 ({period_start.strftime('%m')}??"
            prev_start = prev_end = None
            fallback_label = ""
        else:
            period_start = today_date.replace(day=1)
            period_end = today_date + timedelta(days=1)
            period_label = f"?�번 ??({period_start.strftime('%m')}??"
            last_month_end = period_start - timedelta(days=1)
            prev_start = last_month_end.replace(day=1)
            prev_end = period_start
            fallback_label = "지?�달"
    else:
        return empty("미션 기록", "?�떤 기간??기록??보고 ?��?지 ?�시 물어봐줘.")

    def fetch(start, end):
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT DISTINCT ON (cl.checkin_date)
                           m.mission_name, m.category, m.main_category, m.sub_category,
                           m.difficulty, cl.mission_result, cl.result_reason,
                           cl.checkin_date::text
                    FROM checkin_log cl
                    JOIN missions m ON cl.mission_id = m.mission_id
                    WHERE cl.student_id = %s
                      AND cl.checkin_date >= %s::date
                      AND cl.checkin_date < %s::date
                      AND cl.function_called = 'submit_mission_result'
                      AND cl.mission_result IS DISTINCT FROM 'cancelled'
                    ORDER BY cl.checkin_date, cl.created_at DESC
                """, (student_id, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
                return [dict(r) for r in cur.fetchall()]

    records = fetch(period_start, period_end)
    fallback = False
    if not records and prev_start and prev_end:
        records = fetch(prev_start, prev_end)
        fallback = True

    return {
        "period_label": period_label,
        "records": records,
        "fallback": fallback,
        "fallback_label": fallback_label,
        "need_clarification": False,
        "clarification_message": "",
    }


def get_mission_records(
    student_id: int,
    from_date: str,
    to_date: str,
) -> list[dict]:
    """배정??미션???�짜 범위�?조회?�다. ?�출???�으�?unsubmitted�??�려준?? to_date??exclusive."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                       cl.checkin_id,
                       sdm.student_id,
                       sdm.mission_id,
                       sdm.assigned_date::text AS target_date,
                       COALESCE(cl.mission_result, 'unsubmitted') AS result,
                       cl.result_reason,
                       cl.created_at,
                       sdm.status AS mission_status,
                       m.mission_name,
                       m.category,
                       m.main_category,
                       m.sub_category,
                       m.difficulty
                FROM student_daily_missions sdm
                JOIN missions m ON sdm.mission_id = m.mission_id
                LEFT JOIN LATERAL (
                    SELECT cl.checkin_id, cl.mission_result, cl.result_reason, cl.created_at
                    FROM checkin_log cl
                    WHERE cl.student_id = sdm.student_id
                      AND cl.mission_id = sdm.mission_id
                      AND cl.checkin_date = sdm.assigned_date
                      AND cl.function_called = 'submit_mission_result'
                    ORDER BY cl.created_at DESC
                    LIMIT 1
                ) cl ON TRUE
                WHERE sdm.student_id = %s
                  AND sdm.assigned_date >= %s::date
                  AND sdm.assigned_date < %s::date
                ORDER BY sdm.assigned_date
            """, (student_id, from_date, to_date))
            return [dict(r) for r in cur.fetchall()]


def create_mission_correction_request(
    student_id: int,
    checkin_id: int | None,
    mission_id: int,
    target_date: date,
    current_result: str,
    requested_result: str,
    message: str | None = None,
) -> dict | None:
    """미션 결과??변경하지 ?�고 관리자 ?�인???�청�??�?�한??"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if current_result == "unsubmitted":
                cur.execute("""
                    SELECT 1
                    FROM student_daily_missions sdm
                    WHERE sdm.student_id = %s
                      AND sdm.mission_id = %s
                      AND sdm.assigned_date = %s::date
                      AND NOT EXISTS (
                          SELECT 1
                          FROM checkin_log cl
                          WHERE cl.student_id = sdm.student_id
                            AND cl.mission_id = sdm.mission_id
                            AND cl.checkin_date = sdm.assigned_date
                            AND cl.function_called = 'submit_mission_result'
                      )
                    LIMIT 1
                """, (student_id, mission_id, target_date))
                if not cur.fetchone():
                    return None
                checkin_id = None
            else:
                if checkin_id is None:
                    return None
                cur.execute("""
                    SELECT checkin_id
                    FROM checkin_log
                    WHERE checkin_id = %s
                      AND student_id = %s
                      AND mission_id = %s
                      AND checkin_date = %s::date
                      AND mission_result = %s
                      AND function_called = 'submit_mission_result'
                    LIMIT 1
                """, (checkin_id, student_id, mission_id, target_date, current_result))
                if not cur.fetchone():
                    return None

            cur.execute("""
                INSERT INTO mission_correction_requests (
                    student_id, checkin_id, mission_id, target_date,
                    current_result, requested_result, message
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, student_id, checkin_id, mission_id,
                          target_date::text, current_result, requested_result,
                          message, status, admin_note, created_at, resolved_at
            """, (
                student_id,
                checkin_id,
                mission_id,
                target_date,
                current_result,
                requested_result,
                message.strip() if message and message.strip() else None,
            ))
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def create_user_feedback(
    student_id: int,
    feedback_type: str,
    message: str,
) -> dict | None:
    """???�감/버그/문의??관리자 ?�인?�으로만 ?�?�한??"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM students WHERE student_id = %s LIMIT 1", (student_id,))
            if not cur.fetchone():
                return None

            cur.execute("""
                INSERT INTO user_feedback (student_id, feedback_type, message)
                VALUES (%s, %s, %s)
                RETURNING id, student_id, feedback_type, message,
                          status, admin_note, created_at, resolved_at
            """, (student_id, feedback_type, message.strip()))
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


_DIFFICULTY_ORDER = ["easy", "medium", "hard"]


def find_adjusted_mission(student_id: int, adjustment_type: str, current_mission_id: int) -> dict | None:
    """adjustment_type???�라 ??미션 ?�택. ?�으�?None."""
    today = _kst_today()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT main_category, difficulty FROM missions WHERE mission_id = %s",
                (current_mission_id,),
            )
            current = cur.fetchone()
    if not current:
        return None

    main_category = current["main_category"]
    difficulty = current["difficulty"]

    if adjustment_type == "easier":
        idx = _DIFFICULTY_ORDER.index(difficulty) if difficulty in _DIFFICULTY_ORDER else 1
        target_difficulty = _DIFFICULTY_ORDER[idx - 1] if idx > 0 else difficulty
    elif adjustment_type == "harder":
        idx = _DIFFICULTY_ORDER.index(difficulty) if difficulty in _DIFFICULTY_ORDER else 1
        target_difficulty = _DIFFICULTY_ORDER[idx + 1] if idx < len(_DIFFICULTY_ORDER) - 1 else difficulty
    else:  # change: 같�? ?�이??
        target_difficulty = difficulty

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT mission_id, mission_name, mission_rule
                FROM missions
                WHERE main_category = %s
                  AND difficulty = %s
                  AND is_active = TRUE
                  AND mission_id != %s
                  AND mission_id NOT IN (
                      SELECT mission_id FROM student_daily_missions
                      WHERE student_id = %s
                        AND assigned_date >= %s::date - INTERVAL '7 days'
                        AND assigned_date < %s::date
                  )
                  AND mission_id NOT IN (
                      SELECT old_mission_id FROM mission_changes
                      WHERE student_id = %s
                        AND change_date = %s::date
                      UNION
                      SELECT new_mission_id FROM mission_changes
                      WHERE student_id = %s
                        AND change_date = %s::date
                  )
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (
                    main_category,
                    target_difficulty,
                    current_mission_id,
                    student_id,
                    today,
                    today,
                    student_id,
                    today,
                    student_id,
                    today,
                ),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def save_mission_adjustment(student_id: int, old_mission_id: int, new_mission_id: int) -> None:
    """미션 변�??�력 ?�??mission_changes) + student_daily_missions ?�데?�트."""
    today = _kst_today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mission_changes
                    (student_id, old_mission_id, new_mission_id, change_date,
                     changed_by, sheet_update_status, last_updated_at, created_at)
                VALUES (%s, %s, %s, %s, 'ai', 'pending', NOW(), NOW())
                """,
                (student_id, old_mission_id, new_mission_id, today),
            )
            cur.execute(
                "UPDATE student_daily_missions SET mission_id = %s, updated_at = NOW() "
                "WHERE student_id = %s AND assigned_date = %s",
                (new_mission_id, student_id, today),
            )
        conn.commit()
    try:
        from sheets import sync_daily_status_for_student

        sync_daily_status_for_student(student_id, today)
    except Exception as e:
        print(f"[sheets] mission adjustment sync failed: {e}")


def cancel_last_action(student_id: int, cancel_type: str = "latest") -> str | None:
    """?�늘(KST) ?�당 ?�생??가??최근 ?�동??취소.
    checkin_log(?�출)?� mission_changes(미션 변�? �???최근 것을 찾아 취소?�다.
    반환�? 취소???�동 ?�??('submit' | 'adjustment') ?�는 None(취소??�??�음).
    """
    today = _kst_today()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 가??최근 ?�출 기록
            cur.execute(
                "SELECT checkin_id, created_at FROM checkin_log "
                "WHERE student_id = %s AND checkin_date = %s "
                "AND function_called = 'submit_mission_result' "
                "AND mission_result IS DISTINCT FROM 'cancelled' "
                "ORDER BY created_at DESC LIMIT 1",
                (student_id, today),
            )
            last_submit = cur.fetchone()

            # 가??최근 미션 변�?기록
            cur.execute(
                "SELECT change_id, old_mission_id, created_at FROM mission_changes "
                "WHERE student_id = %s AND change_date = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (student_id, today),
            )
            last_change = cur.fetchone()

        # ?????�으�?취소??�??�음
        if not last_submit and not last_change:
            return None

        # ??최근 ?�동 ?�별
        submit_time = last_submit["created_at"] if last_submit else None
        change_time = last_change["created_at"] if last_change else None

        requested_cancel_type = cancel_type if cancel_type in {"submit", "adjustment", "latest"} else "latest"
        cancelled_type = None
        with conn.cursor() as cur:
            if requested_cancel_type == "submit" and not submit_time:
                return None
            if requested_cancel_type == "adjustment" and not change_time:
                return None

            should_cancel_submit = (
                requested_cancel_type == "submit"
                or (
                    requested_cancel_type == "latest"
                    and submit_time
                    and (not change_time or submit_time >= change_time)
                )
            )

            if should_cancel_submit:
                # ?�출 취소: checkin_log??보존?�고 취소 ?�태�??�시 + status 복원
                cur.execute(
                    """
                    UPDATE checkin_log
                    SET mission_result = 'cancelled',
                        result_reason = COALESCE(result_reason, 'cancelled_by_user'),
                        sheet_update_status = 'pending',
                        last_updated_at = NOW()
                    WHERE checkin_id = %s
                    """,
                    (last_submit["checkin_id"],),
                )
                cur.execute(
                    "UPDATE student_daily_missions SET status = 'assigned', updated_at = NOW() "
                    "WHERE student_id = %s AND assigned_date = %s",
                    (student_id, today),
                )
                cancelled_type = "submit"
            else:
                # 미션 변�?취소: mission_changes ??�� + ?�전 미션 복원
                cur.execute("DELETE FROM mission_changes WHERE change_id = %s", (last_change["change_id"],))
                cur.execute(
                    "UPDATE student_daily_missions SET mission_id = %s, updated_at = NOW() "
                    "WHERE student_id = %s AND assigned_date = %s",
                    (last_change["old_mission_id"], student_id, today),
                )
                cancelled_type = "adjustment"
        conn.commit()
    if cancelled_type:
        try:
            from sheets import sync_daily_status_for_student

            sync_daily_status_for_student(student_id, today)
        except Exception as e:
            print(f"[sheets] cancel sync failed: {e}")
    return cancelled_type


def get_last_action_type(student_id: int) -> str | None:
    """?�늘(KST) ?�당 ?�생??가??최근 ?�동 ?�??반환. 'submit' | 'adjustment' | None."""
    today = _kst_today()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT created_at FROM checkin_log "
                "WHERE student_id = %s AND checkin_date = %s "
                "AND function_called = 'submit_mission_result' "
                "AND mission_result IS DISTINCT FROM 'cancelled' "
                "ORDER BY created_at DESC LIMIT 1",
                (student_id, today),
            )
            last_submit = cur.fetchone()
            cur.execute(
                "SELECT created_at FROM mission_changes "
                "WHERE student_id = %s AND change_date = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (student_id, today),
            )
            last_change = cur.fetchone()

    if not last_submit and not last_change:
        return None
    submit_time = last_submit["created_at"] if last_submit else None
    change_time = last_change["created_at"] if last_change else None
    if submit_time and (not change_time or submit_time >= change_time):
        return "submit"
    return "adjustment"


# ?�?� ?�기기억 (user_memories) ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

def save_mission_review(
    student_id: int,
    mission_id: int,
    rating: int,
    comment: str | None = None,
    review_date: str | None = None,
) -> dict | None:
    """Save or update one daily mission review. activity_key is always read from missions."""
    if not student_id:
        raise ValueError("student_id is required")
    if not mission_id:
        raise ValueError("mission_id is required")
    if rating < 1 or rating > 5:
        raise ValueError("rating must be between 1 and 5")

    target_date = review_date or _kst_today()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT mission_id, activity_key
                FROM missions
                WHERE mission_id = %s
                """,
                (mission_id,),
            )
            mission = cur.fetchone()
            if not mission:
                return None
            activity_key = normalize_activity_key(mission.get("activity_key"))
            if mission.get("activity_key") and not activity_key:
                print(
                    "[MissionReview] invalid activity_key ignored "
                    f"mission_id={mission_id} activity_key={mission.get('activity_key')!r}"
                )

            cur.execute(
                """
                INSERT INTO mission_reviews (
                    student_id,
                    mission_id,
                    review_date,
                    activity_key,
                    rating,
                    comment
                )
                VALUES (%s, %s, %s::date, %s, %s, %s)
                ON CONFLICT (student_id, review_date)
                DO UPDATE SET
                    mission_id = EXCLUDED.mission_id,
                    activity_key = EXCLUDED.activity_key,
                    rating = EXCLUDED.rating,
                    comment = EXCLUDED.comment
                RETURNING *
                """,
                (
                    student_id,
                    mission["mission_id"],
                    target_date,
                    activity_key,
                    rating,
                    comment or "",
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def upsert_user_memory(
    student_id: int,
    subject: str,
    memory_type: str,
    polarity: int | None = None,
) -> dict | None:
    """
    ?�용???�기기억???�??갱신?�다.
    DB 컬럼명�? type?��?�? Python ?�장 type�?구분?�려�?memory_type???�용?�다.
    """
    if memory_type not in {"preference", "difficulty", "restriction"}:
        return None
    subject = (subject or "").strip()
    if not student_id or not subject:
        return None
    if memory_type in {"preference", "difficulty"}:
        subject = normalize_activity_key(subject) or ""
        if not subject:
            return None

    if memory_type == "preference":
        delta = 1 if polarity == 1 else -1 if polarity == -1 else 0
        if delta == 0:
            return None
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO user_memories (student_id, subject, type, score, count, updated_at)
                    VALUES (%s, %s, 'preference', %s, 0, NOW())
                    ON CONFLICT (student_id, subject, type)
                    DO UPDATE SET
                        score = GREATEST(-3, LEAST(3, user_memories.score + EXCLUDED.score)),
                        updated_at = NOW()
                    RETURNING *
                """, (student_id, subject, delta))
                row = cur.fetchone()
            conn.commit()
        return dict(row) if row else None

    if memory_type == "difficulty":
        today = _kst_today()
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO user_memories (student_id, subject, type, score, count, updated_at)
                    VALUES (%s, %s, 'difficulty', 0, 1, NOW())
                    ON CONFLICT (student_id, subject, type)
                    DO UPDATE SET
                        count = CASE
                            WHEN (user_memories.updated_at AT TIME ZONE 'Asia/Seoul')::date < %s::date
                            THEN user_memories.count + 1
                            ELSE user_memories.count
                        END,
                        updated_at = CASE
                            WHEN (user_memories.updated_at AT TIME ZONE 'Asia/Seoul')::date < %s::date
                            THEN NOW()
                            ELSE user_memories.updated_at
                        END
                    RETURNING *
                """, (student_id, subject, today, today))
                row = cur.fetchone()
            conn.commit()
        return dict(row) if row else None

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO user_memories (student_id, subject, type, score, count, updated_at)
                VALUES (%s, %s, 'restriction', 0, 0, NOW())
                ON CONFLICT (student_id, subject, type)
                DO UPDATE SET updated_at = NOW()
                RETURNING *
            """, (student_id, subject))
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def get_relevant_user_memories(student_id: int) -> list[dict]:
    """
    추후 미션 배정/?�터링에?????�심 기억�?조회?�다.
    preference??|score| >= 2, difficulty??count >= 2, restriction?� ?�체 반환.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, student_id, subject, type, score, count, updated_at
                FROM user_memories
                WHERE student_id = %s
                  AND (
                    (type = 'preference' AND ABS(score) >= 2)
                    OR (type = 'difficulty' AND count >= 2)
                    OR type = 'restriction'
                  )
                ORDER BY updated_at DESC, id DESC
            """, (student_id,))
            rows = cur.fetchall()
    return [dict(row) for row in rows]


def get_activity_preferences(student_id: int) -> dict:
    """Return explicit activity preference memories split by score polarity."""
    if not student_id:
        return {"preferred_activity_keys": [], "disliked_activity_keys": []}

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT subject, score
                FROM user_memories
                WHERE student_id = %s
                  AND type = 'preference'
                  AND subject = ANY(%s)
                ORDER BY updated_at DESC, id DESC
            """, (student_id, list(VALID_ACTIVITY_KEYS)))
            rows = cur.fetchall()

    preferred = []
    disliked = []
    for row in rows:
        score = int(row.get("score") or 0)
        subject = row.get("subject")
        if score > 0:
            preferred.append(subject)
        elif score < 0:
            disliked.append(subject)
    return {
        "preferred_activity_keys": preferred,
        "disliked_activity_keys": disliked,
    }


def replace_activity_preferences(
    student_id: int,
    preferred_activity_keys: list[str] | None = None,
    disliked_activity_keys: list[str] | None = None,
) -> dict:
    """Replace the student's explicit activity preferences with the provided set."""
    if not student_id:
        raise ValueError("student_id is required")

    preferred = []
    seen = set()
    for value in preferred_activity_keys or []:
        key = normalize_activity_key(value)
        if key and key not in seen:
            preferred.append(key)
            seen.add(key)

    disliked = []
    disliked_seen = set()
    for value in disliked_activity_keys or []:
        key = normalize_activity_key(value)
        if key and key not in seen and key not in disliked_seen:
            disliked.append(key)
            disliked_seen.add(key)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                DELETE FROM user_memories
                WHERE student_id = %s
                  AND type = 'preference'
                  AND subject = ANY(%s)
            """, (student_id, list(VALID_ACTIVITY_KEYS)))

            rows = []
            for subject, score in [(key, 3) for key in preferred] + [(key, -3) for key in disliked]:
                cur.execute("""
                    INSERT INTO user_memories (student_id, subject, type, score, count, updated_at)
                    VALUES (%s, %s, 'preference', %s, 0, NOW())
                    RETURNING *
                """, (student_id, subject, score))
                row = cur.fetchone()
                if row:
                    rows.append(dict(row))
        conn.commit()

    return {
        "preferred_activity_keys": preferred,
        "disliked_activity_keys": disliked,
        "memories": rows,
    }


# ?�?� 멀?�턴 pending actions ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

VALID_PENDING_ACTION_TYPES = {
    "submit_confirmation",
    "natural_language_confirmation",
    "mission_change_reason",
    "mission_dislike_confirm",
}

CREATABLE_PENDING_ACTION_TYPES = {
    "submit_confirmation",
    "natural_language_confirmation",
}

VALID_RESOLVE_STATUSES = {
    "accepted",
    "rejected",
    "cancelled",
}

VALID_MISSION_CHANGE_REASON_TYPES = {
    "too_easy",
    "too_hard",
    "dislike",
    "cant_do",
    "just_change",
    "onboarding_auto_replace",
    "personalized_change",
    "generated_change",
}


def save_pending_action(student_id: int, action_type: str, payload: dict) -> dict:
    """기존 pending??취소?�고 ??pending action???�?�한??"""
    if action_type not in CREATABLE_PENDING_ACTION_TYPES:
        raise ValueError(f"Invalid action_type: {action_type}")
    if not student_id:
        raise ValueError("student_id is required")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    payload_json = json.dumps(payload, ensure_ascii=False)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                UPDATE pending_actions
                SET status = 'cancelled',
                    resolved_at = NOW()
                WHERE student_id = %s
                  AND status = 'pending'
            """, (student_id,))
            cur.execute("""
                INSERT INTO pending_actions (
                    student_id,
                    action_type,
                    payload,
                    retry_count,
                    status
                )
                VALUES (%s, %s, %s::jsonb, 0, 'pending')
                RETURNING *
            """, (student_id, action_type, payload_json))
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def get_pending_action(student_id: int) -> dict | None:
    """?�생???�재 pending action 1개�? 조회?�다."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, student_id, action_type, payload, retry_count, status, created_at, resolved_at
                FROM pending_actions
                WHERE student_id = %s
                  AND status = 'pending'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            """, (student_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def resolve_pending(pending_id: int, status: str) -> dict | None:
    """pending action??accepted/rejected/cancelled �??�나�?종료?�다."""
    if status not in VALID_RESOLVE_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                UPDATE pending_actions
                SET status = %s,
                    resolved_at = NOW()
                WHERE id = %s
                RETURNING *
            """, (status, pending_id))
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def increment_pending_retry(pending_id: int) -> dict | None:
    """pending action??retry_count�?1 증�??�킨??"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                UPDATE pending_actions
                SET retry_count = retry_count + 1
                WHERE id = %s
                  AND status = 'pending'
                RETURNING *
            """, (pending_id,))
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def save_mission_change_log(student_id: int, mission_id: int, reason_type: str) -> dict | None:
    """미션 변�??�유 로그�??�?�한?? activity_key??mission_id�?백엔?�에??조회?�다."""
    if reason_type not in VALID_MISSION_CHANGE_REASON_TYPES:
        raise ValueError(f"Invalid reason_type: {reason_type}")
    if not student_id:
        raise ValueError("student_id is required")
    if not mission_id:
        raise ValueError("mission_id is required")

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT activity_key FROM missions WHERE mission_id = %s",
                (mission_id,),
            )
            mission = cur.fetchone()
            if not mission:
                return None
            activity_key = normalize_activity_key(mission.get("activity_key"))
            if mission.get("activity_key") and not activity_key:
                print(
                    "[MissionChangeLog] invalid activity_key ignored "
                    f"mission_id={mission_id} activity_key={mission.get('activity_key')!r}"
                )
            cur.execute("""
                INSERT INTO mission_change_logs (
                    student_id,
                    mission_id,
                    activity_key,
                    reason_type
                )
                VALUES (%s, %s, %s, %s)
                RETURNING *
            """, (student_id, mission_id, activity_key, reason_type))
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


# ?�?� 버튼/명시??UI ?�션 ?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�?�

VALID_GENERATED_MISSION_STATUSES = {"draft", "approved", "rejected", "archived", "assigned", "generated_success"}


def insert_generated_mission(generated: dict) -> dict | None:
    """Insert an internally validated real-time generated mission into missions."""
    if not isinstance(generated, dict):
        return None

    activity_key = normalize_activity_key(generated.get("activity_key"))
    if not activity_key:
        return None

    mission_name = " ".join(str(generated.get("mission_name") or "").split())
    mission_rule = str(generated.get("mission_rule") or "").strip()
    if not mission_name or not mission_rule:
        return None

    difficulty = str(generated.get("difficulty") or "easy").strip().lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "easy"

    reward_xp = generated.get("reward_xp")
    try:
        reward_xp = int(reward_xp)
    except (TypeError, ValueError):
        reward_xp = {"easy": 5, "medium": 10, "hard": 12}[difficulty]

    mission_group = " ".join(str(generated.get("mission_group") or "").split()) or None

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO missions (
                    mission_name,
                    category,
                    mission_description,
                    difficulty,
                    is_active,
                    main_category,
                    sub_category,
                    mission_location,
                    reward_xp,
                    mission_group,
                    mission_rule,
                    activity_key
                )
                VALUES (%s, %s, %s, %s, TRUE, %s, %s, %s, %s, %s, %s, %s)
                RETURNING mission_id, mission_name, category, difficulty,
                          main_category, sub_category, mission_location,
                          reward_xp, mission_group, mission_rule, activity_key
                """,
                (
                    mission_name,
                    generated.get("main_category"),
                    mission_rule,
                    difficulty,
                    generated.get("main_category"),
                    generated.get("sub_category"),
                    generated.get("mission_location"),
                    reward_xp,
                    mission_group,
                    mission_rule,
                    activity_key,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def save_generated_mission_assignment(
    student_id: int,
    generated: dict,
    mission_id: int,
    source_reason: str | None = None,
    status: str = "assigned",
) -> dict | None:
    """Save generated_missions as assignment/audit history, not an admin review queue."""
    if status not in VALID_GENERATED_MISSION_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    if not student_id or not mission_id or not isinstance(generated, dict):
        return None

    activity_key = normalize_activity_key(generated.get("activity_key"))
    if not activity_key:
        return None

    mission_name = " ".join(str(generated.get("mission_name") or "").split())
    if not mission_name:
        return None

    difficulty = str(generated.get("difficulty") or "easy").strip().lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "easy"

    reason = "real_time_generated_change"
    if source_reason:
        reason = f"{reason}: {source_reason}"
    reason = f"{reason}; mission_id={mission_id}"

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO generated_missions (
                    student_id,
                    mission_name,
                    mission_rule,
                    activity_keys,
                    difficulty,
                    source_reason,
                    status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    student_id,
                    mission_name,
                    generated.get("mission_rule") or "",
                    [activity_key],
                    difficulty,
                    reason,
                    status,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def save_generated_mission_draft(
    student_id: int,
    mission_title: str,
    mission_description: str | None,
    activity_keys: list[str],
    difficulty: str | None = None,
    generation_reason: str | None = None,
    source: str = "background_personalized",
) -> dict | None:
    """Save a generated mission as draft only; never assign it to today's mission."""
    title = (mission_title or "").strip()
    if not student_id or not title:
        return None

    valid_keys = []
    seen = set()
    for key in activity_keys or []:
        normalized = normalize_activity_key(key)
        if normalized and normalized not in seen:
            seen.add(normalized)
            valid_keys.append(normalized)
    if not valid_keys:
        return None

    normalized_difficulty = (difficulty or "normal").strip().lower()
    if normalized_difficulty == "medium":
        normalized_difficulty = "normal"
    if normalized_difficulty not in {"easy", "normal", "hard"}:
        normalized_difficulty = "normal"

    source_reason = (generation_reason or "").strip()
    if source:
        source_reason = f"{source}: {source_reason}" if source_reason else source

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO generated_missions (
                    student_id,
                    mission_name,
                    mission_rule,
                    activity_keys,
                    difficulty,
                    source_reason,
                    status
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'draft')
                RETURNING *
                """,
                (
                    student_id,
                    title,
                    mission_description or "",
                    valid_keys,
                    normalized_difficulty,
                    source_reason,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def list_generated_mission_drafts(student_id: int, status: str = "draft") -> list[dict]:
    if status not in VALID_GENERATED_MISSION_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, student_id, mission_name, mission_rule, activity_keys,
                       difficulty, source_reason, status, created_at
                FROM generated_missions
                WHERE student_id = %s
                  AND status = %s
                ORDER BY created_at DESC, id DESC
                """,
                (student_id, status),
            )
            rows = cur.fetchall()
    return [dict(row) for row in rows]


def mark_generated_mission_status(generated_mission_id: int, status: str) -> dict | None:
    if status not in VALID_GENERATED_MISSION_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE generated_missions
                SET status = %s
                WHERE id = %s
                RETURNING *
                """,
                (status, generated_mission_id),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


VALID_MISSION_UI_ACTION_TYPES = {
    "mission_change_reason",
    "mission_dislike_confirm",
    "mission_change_method",
    "awaiting_replacement_mission",
}

VALID_MISSION_UI_ACTION_STATUSES = {
    "pending",
    "pending_input",
    "resolved",
    "cancelled",
    "expired",
}

ACTIVE_MISSION_UI_ACTION_STATUSES = {"pending", "pending_input"}


def save_mission_ui_action(
    student_id: int,
    session_id: str,
    action_type: str,
    payload: dict,
    status: str = "pending",
    ttl_minutes: int = 15,
) -> dict:
    """버튼/명시??UI ?�션??1?�성 action_id�??�?�한??"""
    if not student_id:
        raise ValueError("student_id is required")
    if not session_id:
        raise ValueError("session_id is required")
    if action_type not in VALID_MISSION_UI_ACTION_TYPES:
        raise ValueError(f"Invalid action_type: {action_type}")
    if status not in ACTIVE_MISSION_UI_ACTION_STATUSES:
        raise ValueError(f"Invalid active status: {status}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    action_id = str(uuid.uuid4())
    payload_json = json.dumps(payload, ensure_ascii=False)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                UPDATE mission_ui_actions
                SET status = 'cancelled',
                    resolved_at = NOW()
                WHERE student_id = %s
                  AND session_id = %s
                  AND status IN ('pending', 'pending_input')
            """, (student_id, session_id))
            cur.execute("""
                INSERT INTO mission_ui_actions (
                    action_id,
                    student_id,
                    session_id,
                    action_type,
                    payload,
                    status,
                    expires_at
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, NOW() + (%s || ' minutes')::interval)
                RETURNING *
            """, (action_id, student_id, session_id, action_type, payload_json, status, ttl_minutes))
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def get_pending_mission_ui_action(student_id: int, session_id: str) -> dict | None:
    """?�재 ?�션?�서 ?��?중인 UI ?�션 1개�? 조회?�다. 만료???�션?� expired 처리?�다."""
    if not student_id or not session_id:
        return None
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                UPDATE mission_ui_actions
                SET status = 'expired',
                    resolved_at = NOW()
                WHERE student_id = %s
                  AND session_id = %s
                  AND status IN ('pending', 'pending_input')
                  AND expires_at IS NOT NULL
                  AND expires_at < NOW()
            """, (student_id, session_id))
            cur.execute("""
                SELECT action_id, student_id, session_id, action_type, payload,
                       status, created_at, resolved_at, expires_at
                FROM mission_ui_actions
                WHERE student_id = %s
                  AND session_id = %s
                  AND status IN ('pending', 'pending_input')
                ORDER BY created_at DESC
                LIMIT 1
            """, (student_id, session_id))
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def update_mission_ui_action_payload(
    action_id: str,
    student_id: int,
    session_id: str,
    payload: dict,
) -> dict | None:
    """?��?중인 UI action??payload�?갱신?�다."""
    if not action_id or not student_id or not session_id or not isinstance(payload, dict):
        return None
    payload_json = json.dumps(payload, ensure_ascii=False)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                UPDATE mission_ui_actions
                SET payload = %s::jsonb
                WHERE action_id = %s
                  AND student_id = %s
                  AND session_id = %s
                  AND status IN ('pending', 'pending_input')
                  AND (expires_at IS NULL OR expires_at >= NOW())
                RETURNING *
            """, (payload_json, action_id, student_id, session_id))
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def resolve_mission_ui_action(
    action_id: str,
    student_id: int,
    session_id: str,
    status: str = "resolved",
) -> dict | None:
    """?��?중인 UI ?�션??1?�만 종료?�다."""
    if status not in {"resolved", "cancelled", "expired"}:
        raise ValueError(f"Invalid resolve status: {status}")
    if not action_id or not student_id or not session_id:
        return None
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                UPDATE mission_ui_actions
                SET status = CASE
                        WHEN expires_at IS NOT NULL AND expires_at < NOW() THEN 'expired'
                        ELSE %s
                    END,
                    resolved_at = NOW()
                WHERE action_id = %s
                  AND student_id = %s
                  AND session_id = %s
                  AND status IN ('pending', 'pending_input')
                RETURNING *
            """, (status, action_id, student_id, session_id))
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None
