"""Validate the standalone target design without changing the runtime database."""
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def target():
    conn = sqlite3.connect(':memory:')
    conn.executescript((Path(__file__).resolve().parents[1] / 'schema/v2.sql').read_text(encoding='utf-8'))
    yield conn
    conn.close()


def test_historical_cutoff_without_catalogue(target):
    target.execute("INSERT INTO admission_offerings VALUES ('o',2024,'hanoi','GHA01','Program')")
    target.execute("INSERT INTO cutoff_scores VALUES ('o','PT1',25,30,'https://utc.edu.vn','','','Program','t','t')")
    assert target.execute('SELECT count(*) FROM major_catalogue').fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        target.execute("UPDATE cutoff_scores SET score=31")
    with pytest.raises(sqlite3.IntegrityError):
        target.execute("INSERT INTO admission_offerings VALUES ('other',2024,'hanoi','GHA01','Duplicate')")
    with pytest.raises(sqlite3.IntegrityError):
        target.execute("UPDATE cutoff_scores SET method_code='missing'")
    assert target.execute('PRAGMA foreign_key_check').fetchall() == []


def test_embeddings_and_citations_survive_document_deletion(target):
    target.execute("INSERT INTO documents(id,title,source_url,admission_year,campus_code,category,checksum,raw_text,status,created_at,updated_at) VALUES ('d','Title','https://utc.edu.vn',2026,'hanoi','admission','hash','Text','ready','t','t')")
    target.execute("INSERT INTO document_chunks VALUES ('c','d',0,'Text')")
    target.execute("INSERT INTO embedding_models VALUES ('model','google','test-model',2)")
    for vector in ('[1]', '[1,"bad"]', '{}'):
        with pytest.raises(sqlite3.IntegrityError):
            target.execute('INSERT INTO chunk_embeddings VALUES (?,?,?,?)', ('c','model',vector,'t'))
    target.execute("INSERT INTO chunk_embeddings VALUES ('c','model','[1,0]','t')")
    with pytest.raises(sqlite3.IntegrityError):
        target.execute("UPDATE chunk_embeddings SET vector='[1]'")
    with pytest.raises(sqlite3.IntegrityError):
        target.execute("UPDATE embedding_models SET dimensions=3")
    target.execute("INSERT INTO chat_sessions VALUES ('s','token',NULL,'t')")
    target.execute("INSERT INTO messages(id,session_id,role,content,created_at) VALUES ('m','s','assistant','Answer','t')")
    snapshot = '{"title":"Title","content":"Text","citation":1}'
    target.execute('INSERT INTO message_citations VALUES (?,?,?,?)', ('m',1,'c',snapshot))
    target.execute("INSERT INTO feedback VALUES ('f','m',1,'','t')")
    with pytest.raises(sqlite3.IntegrityError):
        target.execute('UPDATE feedback SET rating=0')
    target.execute("DELETE FROM documents WHERE id='d'")
    assert target.execute('SELECT chunk_id,source_snapshot FROM message_citations').fetchone() == (None,snapshot)
    assert target.execute('SELECT count(*) FROM chunk_embeddings').fetchone()[0] == 0
    target.execute("DELETE FROM chat_sessions WHERE id='s'")
    assert target.execute('SELECT count(*) FROM message_citations').fetchone()[0] == 0
    assert target.execute('SELECT count(*) FROM feedback').fetchone()[0] == 0
    assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert target.execute('PRAGMA foreign_key_check').fetchall() == []
