-- Career data chunks and embeddings schema
-- Add to existing database after v2.sql

PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

-- Career job text chunks for RAG
CREATE TABLE IF NOT EXISTS career_chunks (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES career_jobs(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
  content TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(job_id, chunk_index)
) STRICT;

CREATE INDEX IF NOT EXISTS career_chunks_job ON career_chunks(job_id);

-- Career chunk embeddings (reuse embedding_models table from v2.sql)
CREATE TABLE IF NOT EXISTS career_chunk_embeddings (
  chunk_id TEXT NOT NULL REFERENCES career_chunks(id) ON DELETE CASCADE,
  model_id TEXT NOT NULL REFERENCES embedding_models(id),
  vector TEXT NOT NULL CHECK(json_valid(vector)),
  created_at TEXT NOT NULL,
  PRIMARY KEY(chunk_id, model_id)
) STRICT;

-- Trigger to validate embedding dimensions
CREATE TRIGGER IF NOT EXISTS validate_career_embedding_insert
BEFORE INSERT ON career_chunk_embeddings
BEGIN
  SELECT CASE
    WHEN json_array_length(NEW.vector) != (
      SELECT dimensions FROM embedding_models WHERE id = NEW.model_id
    )
    THEN RAISE(ABORT, 'Career embedding dimension mismatch')
  END;
END;

-- RPC function for career semantic search (similar to match_chunks)
-- Note: This needs to be called from Python using custom SQL with json_each
-- SQLite doesn't have native vector search, so we calculate cosine similarity in Python

COMMIT;
