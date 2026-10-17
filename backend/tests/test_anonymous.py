import hashlib

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.localdb import connect


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    settings.cache_clear()
    main.rates.clear()
    with TestClient(main.app) as test_client:
        yield test_client
    settings.cache_clear()
    main.app.dependency_overrides.clear()


def test_chat_sessions_do_not_require_login(client):
    assert client.get('/admin/documents').status_code == 401
    assert client.post('/auth/register', json={}).status_code == 404
    assert client.post('/auth/login', json={}).status_code == 404

    response = client.post('/sessions')
    assert response.status_code == 200
    session = response.json()
    assert len(session['token']) >= 32
    assert client.get('/messages').status_code == 401
    assert client.get('/messages', headers={'X-Session-Token': 'invalid'}).status_code == 401
    assert client.get('/messages', headers={'X-Session-Token': session['token']}).json() == []
    with connect() as conn:
        row = conn.execute('SELECT token_hash FROM chat_sessions WHERE id=?', (session['id'],)).fetchone()
    assert row['token_hash'] == hashlib.sha256(session['token'].encode()).hexdigest()
    assert session['token'] != row['token_hash']


def test_chat_token_isolates_feedback(client):
    first = client.post('/sessions').json()
    second = client.post('/sessions').json()
    with connect() as conn:
        conn.execute('INSERT INTO messages(id,session_id,role,content,sources,created_at) VALUES(?,?,?,?,?,?)',
                     ('00000000-0000-0000-0000-000000000001', first['id'], 'assistant',
                      'Answer', '[]', '2026-01-01'))
    response = client.post('/feedback', headers={'X-Session-Token': second['token']},
                           json={'message_id': '00000000-0000-0000-0000-000000000001', 'rating': 1})
    assert response.status_code == 404
    assert len(client.get('/messages', headers={'X-Session-Token': first['token']}).json()) == 1
    assert client.get('/messages', headers={'X-Session-Token': second['token']}).json() == []


def test_existing_account_database_accepts_new_anonymous_sessions(client, tmp_path):
    import sqlite3

    path = tmp_path / 'utc.sqlite3'
    conn = sqlite3.connect(path)
    try:
        conn.execute('CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, token_version INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)')
        conn.execute('CREATE TABLE chat_sessions (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, user_id TEXT REFERENCES users(id) ON DELETE CASCADE, created_at TEXT NOT NULL)')
        conn.execute('INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)',
                     ('old-user', 'old@example.com', 'hash', '2026-01-01'))
        conn.execute('INSERT INTO chat_sessions(id,token_hash,user_id,created_at) VALUES(?,?,?,?)',
                     ('00000000-0000-0000-0000-000000000002', 'legacy-owned-token-hash',
                      'old-user', '2026-01-01'))
        conn.commit()
    finally:
        conn.close()

    fresh = client.post('/sessions')
    assert fresh.status_code == 200, fresh.text
    with connect() as conn:
        old = conn.execute('SELECT user_id FROM chat_sessions WHERE id=?',
                           ('00000000-0000-0000-0000-000000000002',)).fetchone()
        new = conn.execute('SELECT user_id FROM chat_sessions WHERE id=?',
                           (fresh.json()['id'],)).fetchone()
    assert old['user_id'] == 'old-user'
    assert new['user_id'] is None
    assert client.get('/messages', headers={'X-Session-Token': 'legacy-owned-token-hash'}).status_code == 401