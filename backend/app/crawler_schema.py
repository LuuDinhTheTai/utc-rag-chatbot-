"""Additive crawler staging migration for existing v2 databases."""


def ensure_crawler(conn):
    ensure_jobs(conn)
    version = 'utc_crawler_v1'
    if conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
        ensure_review(conn)
        return
    conn.execute('BEGIN IMMEDIATE')
    try:
        if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
            conn.execute('CREATE TABLE utc_crawl_runs (id TEXT PRIMARY KEY, started_at TEXT NOT NULL, '
                         'finished_at TEXT NOT NULL, report TEXT NOT NULL)')
            conn.execute('CREATE TABLE utc_crawl_items (url TEXT NOT NULL, hash TEXT NOT NULL, '
                         'payload TEXT NOT NULL, status TEXT NOT NULL, seen_at TEXT NOT NULL, '
                         'document_id TEXT REFERENCES documents(id) ON DELETE SET NULL, PRIMARY KEY(url,hash))')
            conn.execute("INSERT INTO schema_migrations VALUES (?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (version,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    ensure_review(conn)


def ensure_review(conn):
    version = 'utc_crawler_review_v1'
    if conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
        return
    conn.execute('BEGIN IMMEDIATE')
    try:
        if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
            for column in ('review_payload TEXT', 'reviewed_by TEXT', 'reviewed_at TEXT', 'error TEXT', 'review_started_at TEXT'):
                conn.execute('ALTER TABLE utc_crawl_items ADD COLUMN ' + column)
            conn.execute("CREATE UNIQUE INDEX utc_review_one_active ON utc_crawl_items(url) WHERE status='approving'")
            conn.execute("INSERT INTO schema_migrations VALUES (?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (version,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def ensure_jobs(conn):
    version = 'utc_crawler_jobs_v1'
    if conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
        return
    conn.execute('BEGIN IMMEDIATE')
    try:
        if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
            conn.execute('CREATE TABLE utc_crawl_jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, '
                         'created_at TEXT NOT NULL, updated_at TEXT NOT NULL, config TEXT NOT NULL, '
                         'report TEXT, error TEXT)')
            conn.execute("CREATE UNIQUE INDEX utc_crawl_one_active ON utc_crawl_jobs ((1)) WHERE status='running'")
            conn.execute("INSERT INTO schema_migrations VALUES (?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (version,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
