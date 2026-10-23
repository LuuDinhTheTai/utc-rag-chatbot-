import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.localdb import connect


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ADMIN_EMAIL', 'root@example.com')
    monkeypatch.setenv('ADMIN_PASSWORD', 'root-password-123456')
    monkeypatch.setenv('RATE_LIMIT_GLOBAL', '100')
    monkeypatch.setenv('RATE_LIMIT_LOGIN', '5')
    settings.cache_clear()
    with TestClient(main.app) as test_client:
        yield test_client
    settings.cache_clear()
    main.app.dependency_overrides.clear()


def sign_in(client, email, password):
    response = client.post('/admin/login', json={'email': email, 'password': password})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['token']}


def test_rbac_and_session_revocation(client):
    root = sign_in(client, 'root@example.com', 'root-password-123456')
    viewer = client.post('/admin/accounts', headers=root, json={
        'email': 'viewer@example.com', 'password': 'viewer-password-123456', 'role': 'student',
    })
    editor = client.post('/admin/accounts', headers=root, json={
        'email': 'editor@example.com', 'password': 'editor-password-123456', 'role': 'lecturer',
    })
    assert viewer.status_code == 201 and editor.status_code == 201
    viewer_headers = sign_in(client, 'viewer@example.com', 'viewer-password-123456')
    editor_headers = sign_in(client, 'editor@example.com', 'editor-password-123456')
    assert client.get('/auth/me', headers=viewer_headers).json()['role'] == 'student'
    assert client.get('/admin/documents', headers=viewer_headers).status_code == 403
    assert client.get('/admin/majors', headers=viewer_headers).status_code == 403
    assert client.get('/admin/accounts', headers=viewer_headers).status_code == 403
    assert client.post('/admin/documents/preview', headers=viewer_headers).status_code == 403
    assert client.post('/admin/majors', headers=viewer_headers, json={}).status_code == 403
    assert client.get('/admin/accounts', headers=editor_headers).status_code == 403
    assert client.post('/admin/majors', headers=editor_headers, json={}).status_code == 422
    assert client.patch('/admin/accounts/' + viewer.json()['id'], headers=root,
                        json={'role': 'lecturer'}).status_code == 200
    assert client.get('/admin/me', headers=viewer_headers).status_code == 401
    changed = sign_in(client, 'viewer@example.com', 'viewer-password-123456')
    assert client.get('/admin/me', headers=changed).json()['role'] == 'lecturer'
    assert client.patch('/admin/accounts/' + viewer.json()['id'], headers=root,
                        json={'is_active': False}).status_code == 200
    assert client.get('/admin/documents', headers=changed).status_code == 401
    assert client.post('/admin/login', json={
        'email': 'viewer@example.com', 'password': 'viewer-password-123456'}).status_code == 401
    assert client.patch('/admin/accounts/' + client.get('/admin/me', headers=root).json()['id'],
                        headers=root, json={'role': 'student'}).status_code == 409


def test_login_and_global_rate_limits(client, monkeypatch):
    monkeypatch.setenv('RATE_LIMIT_LOGIN', '2')
    settings.cache_clear()
    for _ in range(2):
        assert client.post('/admin/login', json={
            'email': 'wrong@example.com', 'password': 'wrong'}).status_code == 401
    limited = client.post('/admin/login', json={
        'email': 'wrong@example.com', 'password': 'wrong'},
        headers={'Origin': settings().frontend_origin})
    assert limited.status_code == 429
    assert int(limited.headers['Retry-After']) > 0
    assert limited.headers['access-control-allow-origin'] == settings().frontend_origin
    assert client.get('/health').status_code == 200
    with TestClient(main.app) as sibling:
        assert sibling.post('/admin/login', json={'email': 'wrong@example.com', 'password': 'wrong'}).status_code == 429
    monkeypatch.setenv('RATE_LIMIT_GLOBAL', '1')
    settings.cache_clear()
    # A fresh IP gives this test a distinct global bucket.
    with TestClient(main.app, client=('different-client', 12345)) as other:
        assert other.get('/health').status_code == 200
        assert other.get('/health').status_code == 429


def test_existing_admin_schema_migrates(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    settings.cache_clear()
    raw = sqlite3.connect(tmp_path / 'utc.sqlite3')
    raw.execute('CREATE TABLE admins (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)')
    raw.execute("INSERT INTO admins VALUES ('legacy','legacy@example.com','hashed')")
    raw.commit()
    raw.close()
    from app.migrations import migrate
    migrate(tmp_path, apply=True, offline=True)
    with connect() as conn:
        row = conn.execute("SELECT role,is_active FROM accounts WHERE id='legacy'").fetchone()
    assert (row['role'], row['is_active']) == ('admin', 1)
    settings.cache_clear()
