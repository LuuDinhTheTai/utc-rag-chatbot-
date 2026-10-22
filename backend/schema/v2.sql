-- Runtime v2 schema. Apply only to an empty database; use migration CLI for v1.
-- SQLite >=3.37 (STRICT tables, JSON functions required).
-- UUIDs and UTC timestamps are supplied by the application.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE schema_migrations (
  version TEXT PRIMARY KEY, applied_at TEXT NOT NULL
) STRICT;
CREATE TABLE accounts (
  id TEXT PRIMARY KEY, email TEXT NOT NULL COLLATE NOCASE UNIQUE,
  display_name TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('student','lecturer','admin')),
  is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
) STRICT;
CREATE TABLE auth_sessions (
  token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL, created_at TEXT NOT NULL
) STRICT;
CREATE INDEX auth_sessions_account ON auth_sessions(account_id);
CREATE INDEX auth_sessions_expiry ON auth_sessions(expires_at);
CREATE TABLE campuses (
  code TEXT PRIMARY KEY CHECK(code IN ('hanoi','hcm')), name TEXT NOT NULL
) STRICT;
INSERT INTO campuses VALUES ('hanoi','Hà Nội'),('hcm','TP. Hồ Chí Minh');
CREATE TABLE admission_offerings (
  id TEXT PRIMARY KEY,
  admission_year INTEGER NOT NULL CHECK(admission_year BETWEEN 2000 AND 2100),
  campus_code TEXT NOT NULL REFERENCES campuses(code), admission_code TEXT NOT NULL,
  program_name TEXT NOT NULL,
  UNIQUE(admission_year,campus_code,admission_code)
) STRICT;
-- A historical cutoff can exist without a complete catalogue entry.
CREATE TABLE major_catalogue (
  id TEXT PRIMARY KEY REFERENCES admission_offerings(id) ON DELETE CASCADE,
  major_code TEXT NOT NULL, name TEXT NOT NULL,
  quota INTEGER CHECK(quota BETWEEN 0 AND 100000), notes TEXT NOT NULL DEFAULT '',
  source_url TEXT NOT NULL, search_text TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
) STRICT;
CREATE TABLE admission_methods (
  code TEXT PRIMARY KEY, name TEXT NOT NULL
) STRICT;
INSERT INTO admission_methods VALUES
  ('PT1','Điểm thi THPT'),('PT2','Học bạ'),('PT3','Đánh giá năng lực'),('PT4','Đánh giá tư duy');
CREATE TABLE offering_methods (
  offering_id TEXT NOT NULL REFERENCES major_catalogue(id) ON DELETE CASCADE,
  method_code TEXT NOT NULL REFERENCES admission_methods(code),
  sort_order INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(offering_id,method_code)
) STRICT;
CREATE TABLE offering_subject_groups (
  offering_id TEXT NOT NULL REFERENCES major_catalogue(id) ON DELETE CASCADE,
  group_code TEXT NOT NULL CHECK(length(group_code) BETWEEN 2 AND 20),
  sort_order INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(offering_id,group_code)
) STRICT;
CREATE TABLE cutoff_scores (
  offering_id TEXT NOT NULL REFERENCES admission_offerings(id) ON DELETE CASCADE,
  method_code TEXT NOT NULL REFERENCES admission_methods(code),
  score REAL NOT NULL, scale INTEGER NOT NULL CHECK(scale IN (30,100,150,1200)),
  source_url TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', search_text TEXT NOT NULL,
  program_name_snapshot TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  CHECK(score > 0 AND score <= scale), PRIMARY KEY(offering_id,method_code)
) STRICT;
CREATE INDEX cutoff_scores_method ON cutoff_scores(method_code,offering_id);
CREATE TABLE documents (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, source_url TEXT NOT NULL,
  admission_year INTEGER NOT NULL CHECK(admission_year BETWEEN 2000 AND 2100),
  campus_code TEXT NOT NULL REFERENCES campuses(code), category TEXT NOT NULL,
  checksum TEXT NOT NULL UNIQUE, raw_text TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('processing','ready','inactive','failed','deleting')),
  error TEXT, created_by TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  storage_path TEXT, original_filename TEXT,
  original_size INTEGER CHECK(original_size >= 0),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
) STRICT;
CREATE INDEX documents_filter ON documents(admission_year,campus_code,status);
CREATE INDEX documents_author ON documents(created_by);
CREATE TABLE document_chunks (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0), content TEXT NOT NULL,
  UNIQUE(document_id,chunk_index)
) STRICT;
CREATE TABLE embedding_models (
  id TEXT PRIMARY KEY, provider TEXT NOT NULL, model_name TEXT NOT NULL,
  dimensions INTEGER NOT NULL CHECK(dimensions > 0),
  UNIQUE(provider,model_name,dimensions)
) STRICT;
CREATE TABLE chunk_embeddings (
  chunk_id TEXT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
  model_id TEXT NOT NULL REFERENCES embedding_models(id),
  vector TEXT NOT NULL CHECK(json_valid(vector)), created_at TEXT NOT NULL,
  PRIMARY KEY(chunk_id,model_id)
) STRICT;
CREATE TRIGGER validate_embedding_insert BEFORE INSERT ON chunk_embeddings
BEGIN
  SELECT CASE WHEN json_type(NEW.vector) != 'array'
    OR json_array_length(NEW.vector) != (SELECT dimensions FROM embedding_models WHERE id=NEW.model_id)
    OR EXISTS (SELECT 1 FROM json_each(NEW.vector) WHERE type NOT IN ('integer','real'))
    THEN RAISE(ABORT,'Invalid embedding dimensions or values') END;
END;
CREATE TRIGGER validate_embedding_update BEFORE UPDATE ON chunk_embeddings
BEGIN
  SELECT CASE WHEN json_type(NEW.vector) != 'array'
    OR json_array_length(NEW.vector) != (SELECT dimensions FROM embedding_models WHERE id=NEW.model_id)
    OR EXISTS (SELECT 1 FROM json_each(NEW.vector) WHERE type NOT IN ('integer','real'))
    THEN RAISE(ABORT,'Invalid embedding dimensions or values') END;
END;
CREATE TRIGGER immutable_embedding_model BEFORE UPDATE OF provider,model_name,dimensions ON embedding_models
BEGIN SELECT RAISE(ABORT,'Create a new embedding model instead'); END;
CREATE INDEX embeddings_model ON chunk_embeddings(model_id,chunk_id);
CREATE TABLE chat_sessions (
  id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
  account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL, created_at TEXT NOT NULL
) STRICT;
CREATE INDEX chat_sessions_account ON chat_sessions(account_id,created_at);
CREATE TRIGGER revoke_deleted_account_chat BEFORE DELETE ON accounts
BEGIN
  UPDATE chat_sessions SET token_hash=lower(hex(randomblob(32))) WHERE account_id=OLD.id;
END;
CREATE TABLE messages (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
  question TEXT, resolved_question TEXT,
  context_year INTEGER CHECK(context_year BETWEEN 2000 AND 2100),
  context_campus TEXT REFERENCES campuses(code),
  supported INTEGER CHECK(supported IN (0,1)), latency_ms INTEGER CHECK(latency_ms >= 0),
  created_at TEXT NOT NULL
) STRICT;
CREATE INDEX messages_session_created ON messages(session_id,created_at,id);
-- Snapshot survives source deletion and re-indexing; live chunk link is optional.
CREATE TABLE message_citations (
  message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  citation INTEGER NOT NULL CHECK(citation > 0),
  chunk_id TEXT REFERENCES document_chunks(id) ON DELETE SET NULL,
  source_snapshot TEXT NOT NULL CHECK(json_valid(source_snapshot) AND json_type(source_snapshot)='object'),
  PRIMARY KEY(message_id,citation)
) STRICT;
CREATE INDEX citations_chunk ON message_citations(chunk_id);
CREATE TABLE feedback (
  id TEXT PRIMARY KEY, message_id TEXT NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
  rating INTEGER NOT NULL CHECK(rating IN (-1,1)), comment TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
) STRICT;
CREATE TABLE freshman_guides (
  id TEXT PRIMARY KEY, cohort TEXT NOT NULL UNIQUE,
  admission_year INTEGER NOT NULL CHECK(admission_year BETWEEN 2000 AND 2100),
  title TEXT NOT NULL, storage_path TEXT NOT NULL,
  is_published INTEGER NOT NULL DEFAULT 1 CHECK(is_published IN (0,1)),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
) STRICT;
CREATE TABLE freshman_items (
  id TEXT PRIMARY KEY, guide_id TEXT NOT NULL REFERENCES freshman_guides(id) ON DELETE CASCADE,
  code TEXT NOT NULL, category TEXT NOT NULL CHECK(category IN ('document','priority')),
  title TEXT NOT NULL, applies_to TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '',
  source_page INTEGER NOT NULL CHECK(source_page > 0), sort_order INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(guide_id,category,code)
) STRICT;
CREATE INDEX freshman_items_order ON freshman_items(guide_id,category,sort_order,code);
CREATE TABLE api_rate_limits (
  key TEXT NOT NULL, window_start INTEGER NOT NULL, count INTEGER NOT NULL CHECK(count >= 0),
  PRIMARY KEY(key,window_start)
) STRICT;
CREATE INDEX api_rate_limits_window ON api_rate_limits(window_start);
INSERT INTO schema_migrations VALUES ('schema_v2',strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
