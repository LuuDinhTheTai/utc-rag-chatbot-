"""Legacy schema upgrades used only on migration staging copies."""
from datetime import datetime, timezone

def now():
    return datetime.now(timezone.utc).isoformat()

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS admins (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'admin' CHECK(role IN ('admin','editor','viewer')), is_active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS admin_sessions (token_hash TEXT PRIMARY KEY, admin_id TEXT NOT NULL REFERENCES admins(id) ON DELETE CASCADE, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, email TEXT NOT NULL COLLATE NOCASE UNIQUE, display_name TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('student','lecturer','admin')), is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_sessions (token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS auth_sessions_account ON auth_sessions(account_id);
CREATE TABLE IF NOT EXISTS api_rate_limits (key TEXT NOT NULL, window_start INTEGER NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(key,window_start));
CREATE INDEX IF NOT EXISTS api_rate_limits_window ON api_rate_limits(window_start);
CREATE TABLE IF NOT EXISTS chat_sessions (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, question TEXT, sources TEXT NOT NULL DEFAULT '[]', supported INTEGER, latency_ms INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, message_id TEXT UNIQUE NOT NULL REFERENCES messages(id) ON DELETE CASCADE, rating INTEGER NOT NULL, comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, title TEXT NOT NULL, source_url TEXT NOT NULL, admission_year INTEGER NOT NULL, campus TEXT NOT NULL, category TEXT NOT NULL, checksum TEXT UNIQUE NOT NULL, raw_text TEXT NOT NULL, status TEXT NOT NULL, chunk_count INTEGER NOT NULL DEFAULT 0, error TEXT, created_by TEXT, storage_path TEXT, original_filename TEXT, original_size INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS document_chunks (id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, chunk_index INTEGER NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL, UNIQUE(document_id, chunk_index));
CREATE INDEX IF NOT EXISTS chunks_document ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS documents_filter ON documents(admission_year,campus,status);
CREATE TABLE IF NOT EXISTS major_catalogue (id TEXT PRIMARY KEY, admission_code TEXT NOT NULL, major_code TEXT NOT NULL, name TEXT NOT NULL, program_name TEXT NOT NULL, admission_year INTEGER NOT NULL, campus TEXT NOT NULL, quota INTEGER, methods TEXT NOT NULL DEFAULT '[]', subject_groups TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, search_text TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(admission_year,campus,admission_code));
CREATE TABLE IF NOT EXISTS cutoff_scores (admission_year INTEGER NOT NULL, campus TEXT NOT NULL CHECK(campus IN ('hanoi','hcm')), admission_code TEXT NOT NULL, program_name TEXT NOT NULL, method TEXT NOT NULL CHECK(method IN ('PT1','PT2','PT3','PT4')), score REAL NOT NULL, scale INTEGER NOT NULL, source_url TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', search_text TEXT NOT NULL, PRIMARY KEY(admission_year,campus,admission_code,method));
CREATE INDEX IF NOT EXISTS cutoff_scores_filters ON cutoff_scores(admission_year,campus,method);
CREATE TABLE IF NOT EXISTS freshman_guides (id TEXT PRIMARY KEY, cohort TEXT UNIQUE NOT NULL, admission_year INTEGER NOT NULL, title TEXT NOT NULL, storage_path TEXT NOT NULL, is_published INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS freshman_items (id TEXT PRIMARY KEY, guide_id TEXT NOT NULL REFERENCES freshman_guides(id) ON DELETE CASCADE, code TEXT NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL, applies_to TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '', source_page INTEGER NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(guide_id,category,code));
"""

def prepare(conn):
    conn.executescript(SCHEMA)
    message_columns = {row['name'] for row in conn.execute('PRAGMA table_info(messages)')}
    for name, kind in [('resolved_question', 'TEXT'), ('context_year', 'INTEGER'), ('context_campus', 'TEXT')]:
        if name not in message_columns:
            conn.execute(f'ALTER TABLE messages ADD COLUMN {name} {kind}')
    conn.execute('CREATE INDEX IF NOT EXISTS messages_session_created ON messages(session_id,created_at)')
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(admins)')}
    if 'role' not in columns:
        conn.execute("ALTER TABLE admins ADD COLUMN role TEXT NOT NULL DEFAULT 'admin' CHECK(role IN ('admin','editor','viewer'))")
    if 'is_active' not in columns:
        conn.execute('ALTER TABLE admins ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1')
    conn.commit()
    # Run once under a write lock. Preserve legacy rows and IDs for audit/foreign keys;
    # legacy session tokens are intentionally not accepted by the new auth module.
    conn.execute('BEGIN IMMEDIATE')
    try:
        if not conn.execute("SELECT 1 FROM schema_migrations WHERE version='accounts_v1'").fetchone():
            timestamp = now()
            conn.execute("INSERT INTO accounts(id,email,display_name,password_hash,role,is_active,created_at,updated_at) "
                         "SELECT id,lower(trim(email)),'',password_hash,CASE role WHEN 'editor' THEN 'lecturer' WHEN 'viewer' THEN 'student' ELSE 'admin' END,is_active,?,? FROM admins",
                         (timestamp, timestamp))
            conn.execute("INSERT INTO schema_migrations VALUES('accounts_v1',?)", (timestamp,))
        session_columns = {row['name'] for row in conn.execute('PRAGMA table_info(chat_sessions)')}
        if 'account_id' not in session_columns:
            conn.execute('ALTER TABLE chat_sessions ADD COLUMN account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE')
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
