-- CREATE EXTENSION IF NOT EXISTS vector;

-- CREATE TABLE IF NOT EXISTS gemini_embeddings (
--     id SERIAL PRIMARY KEY,
--     source_table TEXT NOT NULL,
--     source_pk TEXT,
--     row_index INT NOT NULL,
--     text TEXT NOT NULL,
--     embedding VECTOR,      
--     created_at TIMESTAMPTZ DEFAULT NOW()
-- );

-- CREATE TABLE IF NOT EXISTS qwen_embeddings (
--     id SERIAL PRIMARY KEY,
--     source_table TEXT NOT NULL,
--     source_pk TEXT,
--     row_index INT NOT NULL,
--     text TEXT NOT NULL,
--     embedding VECTOR,
--     created_at TIMESTAMPTZ DEFAULT NOW()
-- );

-- CREATE TABLE IF NOT EXISTS opensearch_sparse_embeddings (
--     id SERIAL PRIMARY KEY,
--     source_table TEXT NOT NULL,
--     source_pk TEXT,
--     row_index INT NOT NULL,
--     text TEXT NOT NULL,
--     embedding JSONB, 
--     created_at TIMESTAMPTZ DEFAULT NOW()
-- );


-- ALTER TABLE materials_qwen
-- ADD COLUMN name_embedding VECTOR,
-- ADD COLUMN description_embedding VECTOR;

-- ALTER TABLE products_qwen
-- ADD COLUMN name_embedding VECTOR,
-- ADD COLUMN description_embedding VECTOR;

-- ALTER TABLE materials_sparse
-- DROP COLUMN name_embedding,
-- DROP COLUMN description_embedding;

-- ALTER TABLE products_sparse
-- DROP COLUMN name_embedding,
-- DROP COLUMN description_embedding;

-- ALTER TABLE materials_sparse
-- ADD COLUMN name_embedding VECTOR,
-- ADD COLUMN description_embedding VECTOR;

-- ALTER TABLE products_sparse
-- ADD COLUMN name_embedding VECTOR,
-- ADD COLUMN description_embedding VECTOR;