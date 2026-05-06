ALTER TABLE missions
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

ALTER TABLE mission_change_logs
ADD COLUMN IF NOT EXISTS activity_key TEXT;

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
