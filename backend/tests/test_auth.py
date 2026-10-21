import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.localdb import connect
from app.security import check_password, password_hash
from scripts.seed_auth import seed


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ADMIN_EMAIL', 'root@example.com')
    monkeypatch.setenv('ADMIN_PASSWORD', 'root-password-123456')
    monkeypatch.setenv('RATE_LIMIT_LOGIN', '100')
    monkeypatch.setenv('RATE_LIMIT_GLOBAL', '1000')
    settings.cache_clear()
    with TestClient(main.app) as client:
        yield client
    settings.cache_clear()
    main.app.dependency_overrides.clear()


def login(client, email='root@example.com', password='root-password-123456'):
    response = client.post('/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['token']}


def student(client, email='student@example.com'):
    response = client.post('/auth/register', json={'email': email, 'display_name': 'Student', 'password': 'student-password-123456'})
    assert response.status_code == 201, response.text
    return login(client, email, 'student-password-123456')


def test_registration_cannot_escalate_and_normalizes_email(client):
    payload = {'email': ' Student@Example.com ', 'display_name': 'Student', 'password': 'student-password-123456'}
    assert client.post('/auth/register', json={**payload, 'role': 'admin'}).status_code == 422
    assert client.post('/auth/register', json={**payload, 'is_active': True}).status_code == 422
    assert client.post('/auth/register', json=payload).status_code == 201
    assert client.post('/auth/register', json={**payload, 'email': 'student@example.com'}).status_code == 409
    headers = login(client, 'STUDENT@example.com', payload['password'])
    assert client.get('/auth/me', headers=headers).json()['role'] == 'student'
    assert client.get('/admin/me', headers=headers).status_code == 403
    assert client.get('/admin/accounts', headers=headers).status_code == 403
    assert client.post('/admin/accounts', headers=headers, json={}).status_code == 403
    with connect() as conn:
        row = conn.execute('SELECT password_hash FROM accounts WHERE email=?', ('student@example.com',)).fetchone()
        assert row['password_hash'] != payload['password']
        assert check_password(payload['password'], row['password_hash'])


def test_guest_public_access_and_bound_chat_ownership(client):
    assert client.get('/auth/me').json()['role'] == 'guest'
    for path in ['/majors', '/cutoffs', '/freshmen']:
        assert client.get(path).status_code == 200
    guest_token = client.post('/sessions').json()['token']
    assert client.get('/messages', headers={'X-Session-Token': guest_token}).status_code == 200
    alice = student(client)
    bob = student(client, 'bob@example.com')
    token = client.post('/sessions', headers=alice).json()['token']
    assert client.get('/messages', headers={**alice, 'X-Session-Token': token}).status_code == 200
    assert client.get('/messages', headers={**bob, 'X-Session-Token': token}).status_code == 403
    assert client.get('/messages', headers={'X-Session-Token': token}).status_code == 403
    assert client.post('/chat', headers={**bob, 'X-Session-Token': token}, json={'question': 'Test'}).status_code == 403


def test_password_change_logout_and_expiry(client):
    headers = student(client)
    second = login(client, 'student@example.com', 'student-password-123456')
    wrong = {'current_password': 'wrong', 'new_password': 'new-student-password-123456'}
    assert client.post('/auth/password', headers=headers, json=wrong).status_code == 400
    assert client.post('/auth/password', headers=headers, json={**wrong, 'current_password': 'student-password-123456'}).status_code == 200
    assert client.get('/auth/me', headers=headers).status_code == 401
    assert client.get('/auth/me', headers=second).status_code == 401
    assert client.post('/auth/login', json={'email': 'student@example.com', 'password': 'student-password-123456'}).status_code == 401
    current = login(client, 'student@example.com', wrong['new_password'])
    with connect() as conn:
        token = current['Authorization'][7:]
        saved = conn.execute('SELECT token_hash FROM auth_sessions').fetchone()[0]
        assert saved == hashlib.sha256(token.encode()).hexdigest()
        conn.execute("UPDATE auth_sessions SET expires_at='2000-01-01'")
    assert client.get('/auth/me', headers=current).status_code == 401
    current = login(client, 'student@example.com', wrong['new_password'])
    assert client.post('/auth/logout', headers=current).status_code == 200
    assert client.get('/auth/me', headers=current).status_code == 401


def test_lecturer_content_and_admin_account_permissions(client):
    root = login(client)
    response = client.post('/admin/accounts', headers=root, json={'email': 'teacher@example.com', 'password': 'teacher-password-123456', 'role': 'lecturer'})
    assert response.status_code == 201
    teacher = login(client, 'teacher@example.com', 'teacher-password-123456')
    for path in ['/admin/documents', '/admin/majors', '/admin/freshmen', '/admin/review']:
        assert client.get(path, headers=teacher).status_code == 200
    assert client.get('/admin/accounts', headers=teacher).status_code == 403
    assert client.patch('/admin/accounts/'+response.json()['id'], headers=teacher, json={'role':'admin'}).status_code == 403
    body = {'admission_code':'TEST123','major_code':'12345','name':'Test major','program_name':'Test program','admission_year':2026,'campus':'hanoi','quota':10,'methods':['PT1'],'subject_groups':['A00'],'source_url':'https://utc.edu.vn/'}
    created = client.post('/admin/majors', headers=teacher, json=body)
    assert created.status_code == 201, created.text
    assert client.delete('/admin/majors/'+created.json()['id'], headers=teacher).status_code == 200
    assert client.patch('/admin/accounts/'+response.json()['id'], headers=root, json={'is_active':False}).status_code == 200
    assert client.get('/admin/documents', headers=teacher).status_code == 401


def test_migration_preserves_legacy_credentials_once(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    settings.cache_clear()
    with sqlite3.connect(tmp_path/'utc.sqlite3') as conn:
        conn.execute('CREATE TABLE admins(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT,is_active INTEGER)')
        for role in ['admin','editor','viewer']:
            conn.execute('INSERT INTO admins VALUES(?,?,?,?,1)', (role, role+'@example.com', password_hash('legacy-password-123456'), role))
    with connect() as conn:
        assert [row[0] for row in conn.execute('SELECT role FROM accounts ORDER BY id')] == ['admin','lecturer','student']
        assert check_password('legacy-password-123456', conn.execute("SELECT password_hash FROM accounts WHERE id='admin'").fetchone()[0])
        conn.execute("UPDATE accounts SET role='student' WHERE id='editor'")
    with connect() as conn:
        assert conn.execute("SELECT role FROM accounts WHERE id='editor'").fetchone()[0] == 'student'
        assert conn.execute('SELECT count(*) FROM accounts').fetchone()[0] == 3
    settings.cache_clear()


def test_seed_has_exactly_three_rows_and_is_idempotent(client):
    created, path = seed()
    assert {item['role'] for item in created} == {'student','lecturer','admin'}
    before = path.read_bytes()
    assert seed()[0] == []
    assert path.read_bytes() == before
    with connect() as conn:
        assert conn.execute('SELECT count(*) FROM accounts').fetchone()[0] == 3
    for row in created:
        headers = login(client, row['email'], row['password'])
        assert client.get('/auth/me', headers=headers).json()['role'] == row['role']


def test_student_registration_does_not_block_admin_bootstrap(client):
    student(client)
    assert client.post('/auth/register', json={'email':'ROOT@example.com','display_name':'Fake admin','password':'student-password-123456'}).status_code == 409
    root = login(client)
    assert client.get('/auth/me', headers=root).json()['role'] == 'admin'
