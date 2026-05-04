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
            'just_change'
        )
    ),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
