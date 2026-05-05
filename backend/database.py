import json
import os
import psycopg2
import psycopg2.extras
from datetime import date, datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

DEMO_MISSION_IDS = [
    2, 12, 16, 25, 29, 38, 43, 51, 62,
    67, 71, 87, 96, 112, 153, 159, 168, 192,
]


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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS demo_mission (
                    order_no INTEGER PRIMARY KEY,
                    mission_id INTEGER NOT NULL REFERENCES missions(mission_id),
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                ALTER TABLE missions
                ADD COLUMN IF NOT EXISTS activity_key TEXT
            """)
            cur.execute("DELETE FROM demo_mission")
            for idx, mission_id in enumerate(DEMO_MISSION_IDS, start=1):
                cur.execute("""
                    INSERT INTO demo_mission (order_no, mission_id, is_active)
                    VALUES (%s, %s, TRUE)
                    ON CONFLICT (order_no) DO UPDATE
                        SET mission_id = EXCLUDED.mission_id,
                            is_active = TRUE
                """, (idx, mission_id))
            cur.execute("SELECT to_regclass('public.student_daily_missions')")
            if cur.fetchone()[0]:
                cur.execute("""
                    ALTER TABLE student_daily_missions
                    ADD COLUMN IF NOT EXISTS assigned_by TEXT DEFAULT 'system'
                """)
            cur.execute("SELECT to_regclass('public.checkin_log')")
            if cur.fetchone()[0]:
                cur.execute("""
                    DELETE FROM checkin_log
                    WHERE checkin_id IN (
                        SELECT checkin_id
                        FROM (
                            SELECT
                                checkin_id,
                                ROW_NUMBER() OVER (
                                    PARTITION BY student_id, checkin_date
                                    ORDER BY created_at DESC NULLS LAST, checkin_id DESC
                                ) AS rn
                            FROM checkin_log
                            WHERE function_called = 'submit_mission_result'
                        ) ranked
                        WHERE rn > 1
                      )
                """)
                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_checkin_submit_once_per_day
                    ON checkin_log (student_id, checkin_date)
                    WHERE function_called = 'submit_mission_result'
                """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pending_mission_suggestions (
                    suggestion_id SERIAL PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    suggested_mission_id INTEGER NOT NULL REFERENCES missions(mission_id),
                    source_text TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    resolved_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_memories (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    subject TEXT NOT NULL,
                    type TEXT NOT NULL CHECK (type IN ('preference', 'difficulty', 'restriction')),
                    score INTEGER DEFAULT 0 CHECK (score BETWEEN -3 AND 3),
                    count INTEGER DEFAULT 0,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (student_id, subject, type)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pending_actions (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    action_type TEXT NOT NULL CHECK (
                        action_type IN (
                            'submit_confirmation',
                            'natural_language_confirmation',
                            'mission_change_reason',
                            'mission_dislike_confirm'
                        )
                    ),
                    payload JSONB NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'accepted', 'rejected', 'cancelled')),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    resolved_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                DO $$
                DECLARE
                    action_type_constraint_name TEXT;
                BEGIN
                    SELECT conname
                      INTO action_type_constraint_name
                      FROM pg_constraint
                     WHERE conrelid = 'pending_actions'::regclass
                       AND contype = 'c'
                       AND pg_get_constraintdef(oid) LIKE '%action_type%'
                     LIMIT 1;

                    IF action_type_constraint_name IS NOT NULL THEN
                        EXECUTE format(
                            'ALTER TABLE pending_actions DROP CONSTRAINT %I',
                            action_type_constraint_name
                        );
                    END IF;

                    ALTER TABLE pending_actions
                    ADD CONSTRAINT pending_actions_action_type_check
                    CHECK (
                        action_type IN (
                            'submit_confirmation',
                            'natural_language_confirmation',
                            'mission_change_reason',
                            'mission_dislike_confirm'
                        )
                    );
                END $$;
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_actions_one_pending_per_student
                ON pending_actions (student_id)
                WHERE status = 'pending'
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mission_change_logs (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    mission_id INTEGER NOT NULL REFERENCES missions(mission_id),
                    activity_key TEXT,
                    reason_type TEXT NOT NULL CHECK (
                        reason_type IN (
                            'too_easy',
                            'too_hard',
                            'dislike',
                            'cant_do',
                            'just_change'
                        )
                    ),
                    created_at TIMESTAMPTZ DEFAULT NOW()
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

def create_demo_student(student_name: str, phone_last4: str) -> dict:
    """
    Create a demo signup student in the existing students table.
    New demo signups are marked with student_note = '신규 가입'.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
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
                    return dict(row)

            cur.execute("""
                INSERT INTO students (
                    student_name,
                    phone_number,
                    age,
                    gender,
                    location,
                    is_active,
                    student_note
                )
                VALUES (%s, %s, NULL, '', '', TRUE, '신규 가입')
                RETURNING *
            """, (student_name, phone_last4))
            student = cur.fetchone()

        conn.commit()

    return dict(student)


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


# ── 오늘의 미션 자동 배정 ─────────────────────────────────────────────────────

def _kst_today() -> str:
    """한국 시간(KST) 기준 오늘 날짜 반환."""
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


# ── 오늘의 미션 (student_daily_missions + missions 테이블) ─────────────────────

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
                       m.mission_rule, sdm.status
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
                       m.mission_rule, sdm.status
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
                       m.mission_rule, sdm.status
                FROM student_daily_missions sdm
                JOIN missions m ON sdm.mission_id = m.mission_id
                WHERE sdm.student_id = %s AND sdm.assigned_date = %s
                """,
                (student_id, today),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def normalize_mission_text(text: str) -> str:
    """미션명 비교용 정규화: 공백 제거 + 소문자화."""
    return (text or "").replace(" ", "").strip().lower()


def find_mission_by_user_text(user_text: str) -> dict | None:
    """
    사용자 발화 안에 missions.mission_name이 정확히 포함되어 있으면 해당 미션 반환.

    예:
    user_text = "채소 반찬 먹기로 미션 바꿔줘"
    mission_name = "채소 반찬 먹기"
    → 공백 제거 후 "채소반찬먹기"가 사용자 발화에 포함되면 정확 매칭으로 판단
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
    사용자 발화에서 2글자 이상 토큰을 뽑아 mission_name과 부분 매칭한다.
    정확 매칭이 없을 때 유사 미션 제안용으로 사용한다.
    """
    cleaned = (user_text or "").strip()
    if not cleaned:
        return None

    remove_words = [
        "미션", "바꿔줘", "바꿔줄래", "변경해줘", "변경", "바꾸고싶어",
        "그럼", "나", "으로", "로", "좀", "해줘", "하는", "거야",
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
    기존 pending 제안은 취소하고 새 제안을 저장한다.
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
    오늘(KST) 미션 결과를 이미 제출했는지 확인.
    checkin_log에 submit_mission_result 기록이 있으면 True.
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
                LIMIT 1
            """, (student_id, today))
            row = cur.fetchone()
    return row is not None


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
                DO NOTHING
                RETURNING checkin_id
                """,
                (student_id, mission_id, today, status,
                 result_reason, detected_function),
            )
            row = cur.fetchone()
            row_id = row[0] if row else None
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
            return empty("하루 기록", "어느 날 기록을 보고 싶은지 오늘, 어제, 그저께처럼 다시 물어봐줘.")
        period_start = resolved_date
        period_end = resolved_date + timedelta(days=1)
        if resolved_date == today_date:
            period_label = f"오늘 ({resolved_date.strftime('%m/%d')})"
        elif resolved_date == today_date - timedelta(days=1):
            period_label = f"어제 ({resolved_date.strftime('%m/%d')})"
        elif resolved_date == today_date - timedelta(days=2):
            period_label = f"그저께 ({resolved_date.strftime('%m/%d')})"
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
                f"지난주 ({period_start.strftime('%m/%d')}~"
                f"{(period_end - timedelta(days=1)).strftime('%m/%d')})"
            )
            prev_start = prev_end = None
            fallback_label = ""
        else:
            period_start = this_week_start
            period_end = today_date + timedelta(days=1)
            period_label = f"이번 주 ({period_start.strftime('%m/%d')}~{today_date.strftime('%m/%d')})"
            prev_start = period_start - timedelta(days=7)
            prev_end = period_start
            fallback_label = "지난주"
    elif query_type == "monthly_summary":
        if target_month:
            period_start = _resolve_target_month(target_month, today_date)
            if not period_start:
                return empty("월간 기록", "몇 월 기록을 보고 싶은지 다시 물어봐줘.")
            period_end = date(period_start.year + (period_start.month // 12), (period_start.month % 12) + 1, 1)
            period_label = period_start.strftime("%Y년 %m월")
            prev_start = prev_end = None
            fallback_label = ""
        elif target_period == "last_month":
            this_month_start = today_date.replace(day=1)
            last_month_end = this_month_start - timedelta(days=1)
            period_start = last_month_end.replace(day=1)
            period_end = this_month_start
            period_label = f"지난달 ({period_start.strftime('%m')}월)"
            prev_start = prev_end = None
            fallback_label = ""
        else:
            period_start = today_date.replace(day=1)
            period_end = today_date + timedelta(days=1)
            period_label = f"이번 달 ({period_start.strftime('%m')}월)"
            last_month_end = period_start - timedelta(days=1)
            prev_start = last_month_end.replace(day=1)
            prev_end = period_start
            fallback_label = "지난달"
    else:
        return empty("미션 기록", "어떤 기간의 기록을 보고 싶은지 다시 물어봐줘.")

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


_DIFFICULTY_ORDER = ["easy", "medium", "hard"]


def find_adjusted_mission(student_id: int, adjustment_type: str, current_mission_id: int) -> dict | None:
    """adjustment_type에 따라 새 미션 선택. 없으면 None."""
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
    else:  # change: 같은 난이도
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
    """미션 변경 이력 저장(mission_changes) + student_daily_missions 업데이트."""
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


def cancel_last_action(student_id: int, cancel_type: str = "latest") -> str | None:
    """오늘(KST) 해당 학생의 가장 최근 행동을 취소.
    checkin_log(제출)와 mission_changes(미션 변경) 중 더 최근 것을 찾아 취소한다.
    반환값: 취소한 행동 타입 ('submit' | 'adjustment') 또는 None(취소할 것 없음).
    """
    today = _kst_today()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 가장 최근 제출 기록
            cur.execute(
                "SELECT checkin_id, created_at FROM checkin_log "
                "WHERE student_id = %s AND checkin_date = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (student_id, today),
            )
            last_submit = cur.fetchone()

            # 가장 최근 미션 변경 기록
            cur.execute(
                "SELECT change_id, old_mission_id, created_at FROM mission_changes "
                "WHERE student_id = %s AND change_date = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (student_id, today),
            )
            last_change = cur.fetchone()

        # 둘 다 없으면 취소할 것 없음
        if not last_submit and not last_change:
            return None

        # 더 최근 행동 판별
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
                # 제출 취소: checkin_log 삭제 + status 복원
                cur.execute("DELETE FROM checkin_log WHERE checkin_id = %s", (last_submit["checkin_id"],))
                cur.execute(
                    "UPDATE student_daily_missions SET status = 'assigned', updated_at = NOW() "
                    "WHERE student_id = %s AND assigned_date = %s",
                    (student_id, today),
                )
                cancelled_type = "submit"
            else:
                # 미션 변경 취소: mission_changes 삭제 + 이전 미션 복원
                cur.execute("DELETE FROM mission_changes WHERE change_id = %s", (last_change["change_id"],))
                cur.execute(
                    "UPDATE student_daily_missions SET mission_id = %s, updated_at = NOW() "
                    "WHERE student_id = %s AND assigned_date = %s",
                    (last_change["old_mission_id"], student_id, today),
                )
                cancelled_type = "adjustment"
        conn.commit()
    return cancelled_type


def get_last_action_type(student_id: int) -> str | None:
    """오늘(KST) 해당 학생의 가장 최근 행동 타입 반환. 'submit' | 'adjustment' | None."""
    today = _kst_today()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT created_at FROM checkin_log "
                "WHERE student_id = %s AND checkin_date = %s "
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


# ── 장기기억 (user_memories) ─────────────────────────────────────────────────

def upsert_user_memory(
    student_id: int,
    subject: str,
    memory_type: str,
    polarity: int | None = None,
) -> dict | None:
    """
    사용자 장기기억을 저장/갱신한다.
    DB 컬럼명은 type이지만, Python 내장 type과 구분하려고 memory_type을 사용한다.
    """
    if memory_type not in {"preference", "difficulty", "restriction"}:
        return None
    subject = (subject or "").strip()
    if not student_id or not subject:
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
    추후 미션 배정/필터링에서 쓸 핵심 기억만 조회한다.
    preference는 |score| >= 2, difficulty는 count >= 2, restriction은 전체 반환.
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


# ── 멀티턴 pending actions ───────────────────────────────────────────────────

VALID_PENDING_ACTION_TYPES = {
    "submit_confirmation",
    "natural_language_confirmation",
    "mission_change_reason",
    "mission_dislike_confirm",
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
}


def save_pending_action(student_id: int, action_type: str, payload: dict) -> dict:
    """기존 pending을 취소하고 새 pending action을 저장한다."""
    if action_type not in VALID_PENDING_ACTION_TYPES:
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
    """학생의 현재 pending action 1개를 조회한다."""
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
    """pending action을 accepted/rejected/cancelled 중 하나로 종료한다."""
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
    """pending action의 retry_count를 1 증가시킨다."""
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
    """미션 변경 이유 로그를 저장한다. activity_key는 mission_id로 백엔드에서 조회한다."""
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
            cur.execute("""
                INSERT INTO mission_change_logs (
                    student_id,
                    mission_id,
                    activity_key,
                    reason_type
                )
                VALUES (%s, %s, %s, %s)
                RETURNING *
            """, (student_id, mission_id, mission.get("activity_key"), reason_type))
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None
