"""Additive planner migration; a write lock makes first-use upgrades safe."""
from pathlib import Path
import sqlite3


def ensure_planner(conn):
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version='planner_v1'").fetchone():
        return
    conn.execute('BEGIN IMMEDIATE')
    try:
        if not conn.execute("SELECT 1 FROM schema_migrations WHERE version='planner_v1'").fetchone():
            statement = ''
            path = Path(__file__).resolve().parents[1] / 'schema/planner.sql'
            for line in path.read_text(encoding='utf-8').splitlines(True):
                statement += line
                if sqlite3.complete_statement(statement):
                    conn.execute(statement)
                    statement = ''
        conn.commit()
    except Exception:
        conn.rollback()
        raise
