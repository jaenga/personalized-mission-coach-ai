-- Runtime support schema for app startup.
-- Run once when setting up or upgrading the database:
--   psql "$DATABASE_URL" -f backend/migrations/003_runtime_schema.sql

CREATE TABLE IF NOT EXISTS session_profiles (
    session_id    TEXT PRIMARY KEY,
    student_id    INTEGER,
    student_name  TEXT,
    db_session_id INTEGER,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS demo_mission (
    order_no INTEGER PRIMARY KEY,
    mission_id INTEGER NOT NULL REFERENCES missions(mission_id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE missions
ADD COLUMN IF NOT EXISTS activity_key TEXT;

ALTER TABLE demo_mission ADD COLUMN IF NOT EXISTS success_criteria TEXT;
ALTER TABLE demo_mission ADD COLUMN IF NOT EXISTS strict_requirements TEXT;
ALTER TABLE demo_mission ADD COLUMN IF NOT EXISTS target_metric TEXT;
ALTER TABLE demo_mission ADD COLUMN IF NOT EXISTS target_value TEXT;
ALTER TABLE demo_mission ADD COLUMN IF NOT EXISTS target_unit TEXT;
ALTER TABLE demo_mission ADD COLUMN IF NOT EXISTS time_condition TEXT;
ALTER TABLE demo_mission ADD COLUMN IF NOT EXISTS allowed_substitutes TEXT;
ALTER TABLE demo_mission ADD COLUMN IF NOT EXISTS denied_substitutes TEXT;

ALTER TABLE student_daily_missions
ADD COLUMN IF NOT EXISTS assigned_by TEXT DEFAULT 'system';

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
          AND mission_result IS DISTINCT FROM 'cancelled'
    ) ranked
    WHERE rn > 1
);

DROP INDEX IF EXISTS uq_checkin_submit_once_per_day;

CREATE UNIQUE INDEX uq_checkin_submit_once_per_day
ON checkin_log (student_id, checkin_date)
WHERE function_called = 'submit_mission_result'
  AND mission_result IS DISTINCT FROM 'cancelled';

CREATE TABLE IF NOT EXISTS pending_mission_suggestions (
    suggestion_id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(student_id),
    suggested_mission_id INTEGER NOT NULL REFERENCES missions(mission_id),
    source_text TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS student_app_state (
    student_id INTEGER PRIMARY KEY REFERENCES students(student_id),
    level INTEGER NOT NULL DEFAULT 1,
    current_xp INTEGER NOT NULL DEFAULT 0,
    ticket_count INTEGER NOT NULL DEFAULT 0,
    heart_count INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS xp_history (
    id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(student_id),
    xp_amount INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    mission_id INTEGER,
    draw_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE xp_history
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS mission_id INTEGER,
    ADD COLUMN IF NOT EXISTS draw_id INTEGER;

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

UPDATE xp_history
   SET source_type = 'mission_success'
 WHERE source_type IS NULL;

ALTER TABLE xp_history
    ALTER COLUMN source_type SET NOT NULL,
    DROP COLUMN IF EXISTS reason,
    DROP COLUMN IF EXISTS source_id;

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

CREATE INDEX IF NOT EXISTS idx_xp_history_student_created
    ON xp_history (student_id, created_at DESC);

CREATE TABLE IF NOT EXISTS draw_runs (
    draw_id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(student_id),
    reward_type TEXT NOT NULL,
    heart_gain INTEGER NOT NULL DEFAULT 0,
    xp_gain INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_draw_runs_student_created
    ON draw_runs (student_id, created_at DESC);

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

CREATE TABLE IF NOT EXISTS attendance_log (
    student_id INTEGER NOT NULL REFERENCES students(student_id),
    attendance_date DATE NOT NULL,
    ticket_awarded INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (student_id, attendance_date)
);

CREATE TABLE IF NOT EXISTS game_runs (
    run_id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(student_id),
    game_type TEXT NOT NULL,
    score INTEGER NOT NULL,
    duration_sec INTEGER NOT NULL DEFAULT 0,
    played_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_game_runs_student_played
    ON game_runs (student_id, played_at DESC);

CREATE INDEX IF NOT EXISTS idx_game_runs_played
    ON game_runs (played_at DESC);

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
);

CREATE TABLE IF NOT EXISTS student_health_notes (
    student_id INTEGER PRIMARY KEY REFERENCES students(student_id) ON DELETE CASCADE,
    allergens JSONB NOT NULL DEFAULT '[]'::jsonb,
    caution_foods JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_memories (
    id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(student_id),
    subject TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('preference', 'difficulty', 'restriction')),
    score INTEGER DEFAULT 0 CHECK (score BETWEEN -3 AND 3),
    count INTEGER DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (student_id, subject, type)
);

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
);

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

CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_actions_one_pending_per_student
ON pending_actions (student_id)
WHERE status = 'pending';

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
);

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

ALTER TABLE mission_change_logs
ADD COLUMN IF NOT EXISTS activity_key TEXT;

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
);

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
);

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
);

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

CREATE INDEX IF NOT EXISTS idx_mission_ui_actions_active
ON mission_ui_actions (student_id, session_id, status, created_at DESC)
WHERE status IN ('pending', 'pending_input');

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
);

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
);

ALTER TABLE mission_correction_requests
ALTER COLUMN checkin_id DROP NOT NULL;

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

CREATE INDEX IF NOT EXISTS idx_mission_correction_requests_student_created
    ON mission_correction_requests (student_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_mission_correction_requests_status_created
    ON mission_correction_requests (status, created_at DESC);

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
);

CREATE INDEX IF NOT EXISTS idx_user_feedback_student_created
    ON user_feedback (student_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_feedback_status_created
    ON user_feedback (status, created_at DESC);
