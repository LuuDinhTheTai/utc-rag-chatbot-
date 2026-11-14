"""Career API schema migration."""
import logging
import sqlite3

log = logging.getLogger('career')


def ensure_career(conn: sqlite3.Connection):
    """
    Ensure career tables exist (additive migration).

    Creates:
        - api_keys: API authentication credentials
        - career_jobs: Career job postings

    This is an additive migration - safe to run multiple times.
    Does not modify existing v2 schema.
    """

    cursor = conn.cursor()

    # Check if already migrated
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='api_keys'"
    )
    if cursor.fetchone():
        # Already migrated
        return

    log.info('career_migration_start')

    try:
        conn.execute('BEGIN IMMEDIATE')

        # ================================================================
        # API KEYS TABLE (V5 Security Model)
        # ================================================================

        conn.execute('''
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,

                -- Key identification (public, can be logged)
                key_hash TEXT NOT NULL UNIQUE,

                -- Secret verification (private, NEVER logged)
                secret_hash TEXT NOT NULL,

                -- Metadata
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',

                -- Permissions (JSON array)
                permissions TEXT NOT NULL CHECK(json_valid(permissions)),

                -- Status
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),

                -- Rate limiting (reserved for Phase 2)
                rate_limit_per_minute INTEGER CHECK(rate_limit_per_minute > 0),

                -- Audit
                created_at TEXT NOT NULL,
                created_by TEXT REFERENCES accounts(id) ON DELETE SET NULL,
                last_used_at TEXT,
                expires_at TEXT,

                CHECK(expires_at IS NULL OR expires_at > created_at)
            ) STRICT
        ''')

        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_api_keys_active
            ON api_keys(is_active) WHERE is_active = 1
        ''')

        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_api_keys_expires
            ON api_keys(expires_at) WHERE expires_at IS NOT NULL
        ''')

        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_api_keys_creator
            ON api_keys(created_by)
        ''')

        # ================================================================
        # CAREER JOBS TABLE (V2 Design Pattern)
        # ================================================================

        conn.execute('''
            CREATE TABLE IF NOT EXISTS career_jobs (
                id TEXT PRIMARY KEY,

                -- Identity (unique constraint)
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,

                -- Denormalized fields for queries ONLY
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                company_name TEXT,

                -- Full payload preservation (single source of truth)
                payload TEXT NOT NULL CHECK(json_valid(payload)),

                -- Content hash for change detection
                content_hash TEXT NOT NULL,

                -- Timestamps
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                UNIQUE(source, external_id)
            ) STRICT
        ''')

        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_career_jobs_source
            ON career_jobs(source)
        ''')

        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_career_jobs_content_hash
            ON career_jobs(content_hash)
        ''')

        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_career_jobs_title
            ON career_jobs(title)
        ''')

        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_career_jobs_company
            ON career_jobs(company_name)
        ''')

        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_career_jobs_created
            ON career_jobs(created_at DESC)
        ''')

        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_career_jobs_updated
            ON career_jobs(updated_at DESC)
        ''')

        # ================================================================
        # MIGRATION MARKER
        # ================================================================

        conn.execute('''
            INSERT OR IGNORE INTO schema_migrations (version, applied_at)
            VALUES ('career_v1', ?)
        ''', (conn.execute('SELECT datetime("now")').fetchone()[0],))

        conn.commit()

        log.info('career_migration_complete')

    except Exception as exc:
        conn.rollback()
        log.error('career_migration_failed error=%s', type(exc).__name__)
        raise
