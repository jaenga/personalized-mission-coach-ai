ALTER TABLE missions
ADD COLUMN IF NOT EXISTS activity_key TEXT;

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

CREATE INDEX IF NOT EXISTS idx_mission_ui_actions_active
ON mission_ui_actions (student_id, session_id, status, created_at DESC)
WHERE status IN ('pending', 'pending_input');
