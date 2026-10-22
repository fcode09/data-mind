-- Optional RAG enhancement; apply only when pgvector is installed.
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding vector(384);
-- Exact vector search is intentional for the small SOP corpus; no ANN recall loss.
