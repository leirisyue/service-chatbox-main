-- Migration script to create user_preferences table
-- Run this in your PostgreSQL database

CREATE TABLE IF NOT EXISTS user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    session_id TEXT NOT NULL,
    product_headcode TEXT NOT NULL,
    product_vector VECTOR(768),           -- Vector embedding của sản phẩm
    interaction_type TEXT NOT NULL,       -- 'view', 'like', 'dislike', etc.
    weight FLOAT DEFAULT 1.0,             -- Trọng số của tương tác
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Index for faster queries
CREATE INDEX IF NOT EXISTS idx_user_preferences_session 
ON user_preferences(session_id);

CREATE INDEX IF NOT EXISTS idx_user_preferences_product 
ON user_preferences(product_headcode);

CREATE INDEX IF NOT EXISTS idx_user_preferences_interaction 
ON user_preferences(interaction_type);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_user_preferences_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_user_preferences_timestamp
BEFORE UPDATE ON user_preferences
FOR EACH ROW
EXECUTE FUNCTION update_user_preferences_timestamp();
