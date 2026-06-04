-- Persist /chat/stream debug payload alongside assistant messages so that
-- the PipelineDebugPanel can be restored after a page refresh.
-- Run once when updating an existing database:
--   psql "$DATABASE_URL" -f backend/migrations/005_chat_debug.sql

CREATE TABLE IF NOT EXISTS chat_debug (
    message_id  INTEGER PRIMARY KEY
                REFERENCES chat_messages(message_id) ON DELETE CASCADE,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
