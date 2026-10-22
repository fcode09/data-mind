-- Require provenance before semantic retrieval can use an embedding.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_model text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_revision text;
INSERT INTO schema_migrations(version) VALUES ('003_embedding_provenance') ON CONFLICT DO NOTHING;
