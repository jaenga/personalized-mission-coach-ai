import json
import os
import random
import psycopg2
import psycopg2.extras
from psycopg2.extras import Json
import uuid
from datetime import date, datetime, timezone, timedelta
from dotenv import load_dotenv

from activity_keys import VALID_ACTIVITY_KEYS, normalize_activity_key

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

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
            # demo_mission 시트 메타데이터 컬럼 (값은 DB에서 직접 관리)
            for col in _DEMO_MISSION_METADATA_COLUMNS:
                cur.execute(
                    f"ALTER TABLE demo_mission ADD COLUMN IF NOT EXISTS {col} TEXT"
                )
            # mission_id/is_active만 동기화. 메타데이터 컬럼은 보존(DB에서 직접 관리).
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
                            'just_change',
                            'onboarding_auto_replace',
                            'personalized_change',
                            'generated_change'
                        )
                    ),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                DO $$
                DECLARE
                    constraint_name TEXT;
                BEGIN
                    SELECT conname
                      INTO constraint_name
                      FROM pg_constraint
                     WHERE conrelid = 'mission_change_logs'::regclass
                       AND contype = 'c'
                       AND pg_get_constraintdef(oid) LIKE '%reason_type%'
                     LIMIT 1;

                    IF constraint_name IS NOT NULL THEN
                        EXECUTE format(
                            'ALTER TABLE mission_change_logs DROP CONSTRAINT %I',
                            constraint_name
                        );
                    END IF;

                    ALTER TABLE mission_change_logs
                    ADD CONSTRAINT mission_change_logs_reason_type_check
                    CHECK (
                        reason_type IN (
                            'too_easy',
                            'too_hard',
                            'dislike',
                            'cant_do',
                            'just_change',
                            'onboarding_auto_replace',
                            'personalized_change',
                            'generated_change'
                        )
                    );
                END $$;
            """)
            cur.execute("""
                ALTER TABLE mission_change_logs
                ADD COLUMN IF NOT EXISTS activity_key TEXT
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mission_reviews (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    mission_id INTEGER NOT NULL REFERENCES missions(mission_id),
                    review_date DATE NOT NULL,
                    activity_key TEXT,
                    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
                    comment TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (student_id, review_date)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS weekly_share_prompts (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    week_start DATE NOT NULL,
                    week_end DATE NOT NULL,
                    prompt_shown_at TIMESTAMPTZ DEFAULT NOW(),
                    dismissed_at TIMESTAMPTZ,
                    shared_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (student_id, week_start)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS generated_missions (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER REFERENCES students(student_id),
                    mission_name TEXT NOT NULL,
                    mission_rule TEXT,
                    activity_keys TEXT[],
                    difficulty TEXT,
                    source_reason TEXT,
                    status TEXT DEFAULT 'draft',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mission_ui_actions (
                    action_id TEXT PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    session_id TEXT NOT NULL,
                    action_type TEXT NOT NULL CHECK (
                        action_type IN (
                            'mission_change_reason',
                            'mission_dislike_confirm',
                            'mission_change_method',
                            'awaiting_replacement_mission'
                        )
                    ),
                    payload JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'pending_input', 'resolved', 'cancelled', 'expired')),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    resolved_at TIMESTAMPTZ,
                    expires_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                DO $$
                DECLARE
                    constraint_name TEXT;
                BEGIN
                    SELECT conname
                      INTO constraint_name
                      FROM pg_constraint
                     WHERE conrelid = 'mission_ui_actions'::regclass
                       AND contype = 'c'
                       AND pg_get_constraintdef(oid) LIKE '%action_type%'
                     LIMIT 1;

                    IF constraint_name IS NOT NULL THEN
                        EXECUTE format(
                            'ALTER TABLE mission_ui_actions DROP CONSTRAINT %I',
                            constraint_name
                        );
                    END IF;

                    ALTER TABLE mission_ui_actions
                    ADD CONSTRAINT mission_ui_actions_action_type_check
                    CHECK (
                        action_type IN (
                            'mission_change_reason',
                            'mission_dislike_confirm',
                            'mission_change_method',
                            'awaiting_replacement_mission'
                        )
                    );
                END $$;
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_mission_ui_actions_active
                ON mission_ui_actions (student_id, session_id, status, created_at DESC)
                WHERE status IN ('pending', 'pending_input')
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mission_correction_requests (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    checkin_id INTEGER REFERENCES checkin_log(checkin_id),
                    mission_id INTEGER NOT NULL REFERENCES missions(mission_id),
                    target_date DATE NOT NULL,
                    current_result TEXT NOT NULL CHECK (
                        current_result IN ('success', 'failure', 'completed', 'fail', 'unsubmitted')
                    ),
                    requested_result TEXT NOT NULL CHECK (
                        requested_result IN ('success', 'failure', 'fail', 'other')
                    ),
                    message TEXT,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK (
                        status IN ('pending', 'in_review', 'resolved', 'rejected')
                    ),
                    admin_note TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    resolved_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                ALTER TABLE mission_correction_requests
                ALTER COLUMN checkin_id DROP NOT NULL
            """)
            cur.execute("""
                DO $$
                DECLARE
                    constraint_name TEXT;
                BEGIN
                    SELECT conname
                      INTO constraint_name
                      FROM pg_constraint
                     WHERE conrelid = 'mission_correction_requests'::regclass
                       AND contype = 'c'
                       AND pg_get_constraintdef(oid) LIKE '%current_result%'
                     LIMIT 1;

                    IF constraint_name IS NOT NULL THEN
                        EXECUTE format(
                            'ALTER TABLE mission_correction_requests DROP CONSTRAINT %I',
                            constraint_name
                        );
                    END IF;

                    ALTER TABLE mission_correction_requests
                    ADD CONSTRAINT mission_correction_requests_current_result_check
                    CHECK (current_result IN ('success', 'failure', 'completed', 'fail', 'unsubmitted'));
                END $$;
            """)
            cur.execute("""
                DO $$
                DECLARE
                    constraint_name TEXT;
                BEGIN
                    SELECT conname
                      INTO constraint_name
                      FROM pg_constraint
                     WHERE conrelid = 'mission_correction_requests'::regclass
                       AND contype = 'c'
                       AND pg_get_constraintdef(oid) LIKE '%requested_result%'
                     LIMIT 1;

                    IF constraint_name IS NOT NULL THEN
                        EXECUTE format(
                            'ALTER TABLE mission_correction_requests DROP CONSTRAINT %I',
                            constraint_name
                        );
                    END IF;

                    ALTER TABLE mission_correction_requests
                    ADD CONSTRAINT mission_correction_requests_requested_result_check
                    CHECK (requested_result IN ('success', 'failure', 'fail', 'other'));
                END $$;
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_mission_correction_requests_student_created
                    ON mission_correction_requests (student_id, created_at DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_mission_correction_requests_status_created
                    ON mission_correction_requests (status, created_at DESC)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_feedback (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    feedback_type TEXT NOT NULL CHECK (
                        feedback_type IN ('app_feedback', 'bug_report', 'inquiry', 'other')
                    ),
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK (
                        status IN ('pending', 'in_review', 'resolved', 'rejected')
                    ),
                    admin_note TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    resolved_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_feedback_student_created
                    ON user_feedback (student_id, created_at DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_feedback_status_created
                    ON user_feedback (status, created_at DESC)
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


def delete_student_completely(student_id: int) -> bool:
    """탈퇴 처리: 학생과 학생을 참조하는 모든 데이터를 한 트랜잭션에서 삭제.

    FK 의존성 순서로 삭제하며, students 행이 존재하지 않으면 False 반환.
    """
    if not student_id:
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM students WHERE student_id = %s", (student_id,))
            if cur.fetchone() is None:
                return False

            # chat_messages는 chat_sessions.session_id를 참조하므로 먼저 삭제.
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

            # xp_history는 draw_runs(draw_id)를 참조하므로 draw_runs보다 먼저.
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
            cur.execute("DELETE FROM checkin_log WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM student_daily_missions WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM student_app_state WHERE student_id = %s", (student_id,))
            cur.execute("DELETE FROM student_health_notes WHERE student_id = %s", (student_id,))

            cur.execute("DELETE FROM students WHERE student_id = %s", (student_id,))
        conn.commit()

    return True


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


def get_mission_records(
    student_id: int,
    from_date: str,
    to_date: str,
) -> list[dict]:
    """배정된 미션을 날짜 범위로 조회한다. 제출이 없으면 unsubmitted로 내려준다. to_date는 exclusive."""
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
    """미션 결과는 변경하지 않고 관리자 확인용 요청만 저장한다."""
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
    """앱 소감/버그/문의는 관리자 확인용으로만 저장한다."""
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
    사용자 장기기억을 저장/갱신한다.
    DB 컬럼명은 type이지만, Python 내장 type과 구분하려고 memory_type을 사용한다.
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


# ── 멀티턴 pending actions ───────────────────────────────────────────────────

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
    """기존 pending을 취소하고 새 pending action을 저장한다."""
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


# ── 버튼/명시적 UI 액션 ───────────────────────────────────────────────────────

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
    """버튼/명시적 UI 액션을 1회성 action_id로 저장한다."""
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
    """현재 세션에서 대기 중인 UI 액션 1개를 조회한다. 만료된 액션은 expired 처리한다."""
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
    """대기 중인 UI action의 payload만 갱신한다."""
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
    """대기 중인 UI 액션을 1회만 종료한다."""
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
