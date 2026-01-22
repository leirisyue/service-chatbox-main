-- Migration script to create chat_histories table
-- Run this in your PostgreSQL database

CREATE TABLE IF NOT EXISTS chat_histories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    email TEXT NOT NULL,
    session_id TEXT NOT NULL,
    session_name TEXT,
    
    chat_date DATE NOT NULL,          -- ngày chat (YYYY-MM-DD)
    time_block SMALLINT NOT NULL,     -- 1 = 0-12h, 2 = 12-24h
    
    history JSONB NOT NULL,
    isDeleted BOOLEAN DEFAULT FALSE,           -- toàn bộ Q&A: [{"q": "...", "a": "...", "timestamp": "..."}]
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE (email, session_id, chat_date, time_block)
);

-- Index for faster queries
CREATE INDEX IF NOT EXISTS idx_chat_histories_email_session 
ON chat_histories(email, session_id);

CREATE INDEX IF NOT EXISTS idx_chat_histories_date 
ON chat_histories(chat_date);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_chat_histories_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_chat_histories_timestamp
BEFORE UPDATE ON chat_histories
FOR EACH ROW
EXECUTE FUNCTION update_chat_histories_timestamp();
