import os
import random
import psycopg2
import psycopg2.extras
from psycopg2.extras import Json
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
                CREATE TABLE IF NOT EXISTS student_app_state (
                    student_id INTEGER PRIMARY KEY REFERENCES students(student_id),
                    level INTEGER NOT NULL DEFAULT 1,
                    current_xp INTEGER NOT NULL DEFAULT 0,
                    ticket_count INTEGER NOT NULL DEFAULT 0,
                    heart_count INTEGER NOT NULL DEFAULT 1,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS xp_history (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    xp_amount INTEGER NOT NULL,
                    source_type TEXT NOT NULL,
                    mission_id INTEGER,
                    draw_id INTEGER,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                ALTER TABLE xp_history
                    ADD COLUMN IF NOT EXISTS source_type TEXT,
                    ADD COLUMN IF NOT EXISTS mission_id INTEGER,
                    ADD COLUMN IF NOT EXISTS draw_id INTEGER
            """)
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                          FROM information_schema.columns
                         WHERE table_schema = 'public'
                           AND table_name = 'xp_history'
                           AND column_name = 'reason'
                    ) THEN
                        EXECUTE 'UPDATE xp_history SET source_type = reason WHERE source_type IS NULL';
                    END IF;

                    IF EXISTS (
                        SELECT 1
                          FROM information_schema.columns
                         WHERE table_schema = 'public'
                           AND table_name = 'xp_history'
                           AND column_name = 'source_id'
                    ) THEN
                        EXECUTE $SQL$
                            UPDATE xp_history
                               SET mission_id = source_id
                             WHERE mission_id IS NULL
                               AND source_type = 'mission_success'
                        $SQL$;
                        EXECUTE $SQL$
                            UPDATE xp_history
                               SET draw_id = source_id
                             WHERE draw_id IS NULL
                               AND source_type = 'draw_reward'
                        $SQL$;
                    END IF;
                END $$;
            """)
            cur.execute("""
                UPDATE xp_history
                   SET source_type = 'mission_success'
                 WHERE source_type IS NULL
            """)
            cur.execute("""
                ALTER TABLE xp_history
                    ALTER COLUMN source_type SET NOT NULL,
                    DROP COLUMN IF EXISTS reason,
                    DROP COLUMN IF EXISTS source_id
            """)
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                          FROM pg_constraint
                         WHERE conname = 'xp_history_source_check'
                    ) THEN
                        ALTER TABLE xp_history
                            ADD CONSTRAINT xp_history_source_check CHECK (
                                (
                                    source_type = 'mission_success'
                                    AND mission_id IS NOT NULL
                                    AND draw_id IS NULL
                                )
                                OR
                                (
                                    source_type = 'draw_reward'
                                    AND draw_id IS NOT NULL
                                    AND mission_id IS NULL
                                )
                            ) NOT VALID;
                    END IF;
                END $$;
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_xp_history_student_created
                    ON xp_history (student_id, created_at DESC)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS draw_runs (
                    draw_id SERIAL PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    reward_type TEXT NOT NULL,
                    heart_gain INTEGER NOT NULL DEFAULT 0,
                    xp_gain INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_draw_runs_student_created
                    ON draw_runs (student_id, created_at DESC)
            """)
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                          FROM pg_constraint
                         WHERE conname = 'xp_history_mission_id_fkey'
                    ) THEN
                        ALTER TABLE xp_history
                            ADD CONSTRAINT xp_history_mission_id_fkey
                            FOREIGN KEY (mission_id) REFERENCES missions(mission_id) NOT VALID;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1
                          FROM pg_constraint
                         WHERE conname = 'xp_history_draw_id_fkey'
                    ) THEN
                        ALTER TABLE xp_history
                            ADD CONSTRAINT xp_history_draw_id_fkey
                            FOREIGN KEY (draw_id) REFERENCES draw_runs(draw_id) NOT VALID;
                    END IF;
                END $$;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS attendance_log (
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    attendance_date DATE NOT NULL,
                    ticket_awarded INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (student_id, attendance_date)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS game_runs (
                    run_id SERIAL PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    game_type TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    duration_sec INTEGER NOT NULL DEFAULT 0,
                    played_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_game_runs_student_played
                    ON game_runs (student_id, played_at DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_game_runs_played
                    ON game_runs (played_at DESC)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lesson_progress (
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    lesson_id TEXT NOT NULL,
                    current_step INTEGER NOT NULL DEFAULT 0,
                    edu_done BOOLEAN NOT NULL DEFAULT FALSE,
                    quiz_done BOOLEAN NOT NULL DEFAULT FALSE,
                    quiz_score INTEGER,
                    completed_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (student_id, lesson_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS student_health_notes (
                    student_id INTEGER PRIMARY KEY REFERENCES students(student_id) ON DELETE CASCADE,
                    allergens JSONB NOT NULL DEFAULT '[]'::jsonb,
                    caution_foods JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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


def _ensure_student_app_state(cur, student_id: int) -> None:
    cur.execute("""
        INSERT INTO student_app_state (student_id)
        VALUES (%s)
        ON CONFLICT (student_id) DO NOTHING
    """, (student_id,))


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
                    _ensure_student_app_state(cur, row["student_id"])
                    conn.commit()
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
            _ensure_student_app_state(cur, student["student_id"])

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
                       m.mission_rule, m.mission_description, sdm.status
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


# ── 레벨/XP 계산 ──────────────────────────────────────────────────────────────
# 누적 XP 임계값: key = 그 레벨에 도달하기 위해 필요한 누적 XP
# 프론트 LEVEL_THRESHOLDS와 정확히 일치해야 함.
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
    미션 성공 보상 지급. 단일 트랜잭션:
      1) 미션의 reward_xp 조회 (없으면 difficulty 기반 fallback)
      2) student_app_state UPSERT — current_xp += gain, level 재계산, ticket_count += 1
      3) xp_history INSERT — source_type='mission_success', mission_id=mission_id

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
    """가챠 보상 분포 (프론트 rollReward와 동일):
       - 첫 뽑기: 하트 1-2 확정
       - 이후: 40% 하트(1-2), 40% XP(3-5), 20% 하트+XP
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
    가챠 한 판 처리. 단일 트랜잭션:
      1) student_app_state FOR UPDATE — 티켓 ≥1 검증
      2) 오늘(KST) draw_runs 조회 → first_of_day 판정
      3) 보상 굴림 (서버 전속)
      4) app_state 업데이트 — ticket -1, heart += gain (cap), xp += gain (level 재계산)
      5) draw_runs INSERT → draw_id
      6) xp_gain > 0 이면 xp_history INSERT (source_type='draw_reward', draw_id=draw_id)

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
    오늘(KST) 첫 출석이면 ticket +1. 두 번째 이후는 no-op.

    attendance_log의 (student_id, attendance_date) PRIMARY KEY로 하루 1회 보장.

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


# ── 경험치 랭킹 ──────────────────────────────────────────────────────────────

_KST = timezone(timedelta(hours=9))


def _period_start_utc(period: str) -> datetime | None:
    """
    'week' = 이번 주 월요일 00:00 KST
    'month' = 이번 달 1일 00:00 KST
    'all' = None (필터 없음)
    UTC로 변환해서 반환.
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
    기간 내 xp_history 합계 기준 랭킹.
    student_app_state의 모든 학생을 LEFT JOIN해서, 기간에 XP 못 받은 학생도 0으로 포함.
    동률은 level DESC, current_xp DESC로 깸.
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


# ── 게임 기록 / 랭킹 ─────────────────────────────────────────────────────────

def record_game_run(
    student_id: int,
    game_type: str,
    score: int,
    duration_sec: int = 0,
) -> dict:
    """게임 한 판 기록. Returns inserted row."""
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
    기간 내 game_runs MAX(score) 기준 랭킹.
    student_app_state의 모든 학생을 LEFT JOIN — 미플레이도 best_score=0, plays=0으로 포함.
    동률은 plays DESC, level DESC, student_id ASC로 깸.
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


# ── 학습 진행도 ───────────────────────────────────────────────────────────────

_QUIZ_TICKET_REWARD = 1


def get_lesson_progress(student_id: int) -> list[dict]:
    """학생의 모든 lesson 진행도. 없으면 빈 리스트."""
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
    부분 업데이트. None은 기존 값 유지. (student_id, lesson_id)에 row 없으면 새로 만듦.
    quiz_done이 처음 True가 될 때 completed_at 자동 세팅.
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
    퀴즈 완료 처리. 첫 완료면 ticket +1 지급 (idempotent — 두 번째부터는 상태만 갱신).

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
    """학생 건강노트 최신 값. 없으면 None."""
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
    """학생 건강노트를 student_id 기준으로 1개만 저장."""
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
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (main_category, target_difficulty, current_mission_id, student_id, today, today),
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
