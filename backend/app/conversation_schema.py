"""Transactional conversation metadata + FTS5 backfill for existing sessions."""
from pathlib import Path
import sqlite3


def ensure_conversations(conn):
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version='conversations_v1'").fetchone():
        return
    conn.execute('BEGIN IMMEDIATE')
    try:
        if not conn.execute("SELECT 1 FROM schema_migrations WHERE version='conversations_v1'").fetchone():
            statement = ''
            for line in (Path(__file__).resolve().parents[1]/'schema/conversations.sql').read_text().splitlines(True):
                statement += line
                if sqlite3.complete_statement(statement):
                    conn.execute(statement)
                    statement = ''
        conn.commit()
    except Exception:
        conn.rollback()
        raise
