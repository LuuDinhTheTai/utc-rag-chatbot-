"""Additive, transactional migration; legacy messages keep null routing metadata."""


def ensure_routing(conn):
    version = 'question_routing_v1'
    if conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
        return
    conn.execute('BEGIN IMMEDIATE')
    try:
        if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
            conn.execute('ALTER TABLE messages ADD COLUMN intent TEXT')
            conn.execute('ALTER TABLE messages ADD COLUMN response_kind TEXT')
            conn.execute('ALTER TABLE messages ADD COLUMN router_version TEXT')
            conn.execute("INSERT INTO schema_migrations VALUES (?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (version,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
