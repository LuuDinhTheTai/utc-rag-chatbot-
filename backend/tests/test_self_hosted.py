import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.localdb import connect


@pytest.fixture
def self_hosted(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ADMIN_EMAIL', 'admin@example.com')
    monkeypatch.setenv('ADMIN_PASSWORD', 'strong-test-password-123')
    monkeypatch.setenv('GOOGLE_API_KEY', 'test-only-key')
    monkeypatch.setenv('EMBEDDING_DIMENSIONS', '3')
    settings.cache_clear()
    with TestClient(main.app) as client:
        login = client.post('/admin/login', json={
            'email': 'admin@example.com', 'password': 'strong-test-password-123'})
        assert login.status_code == 200
        yield client, {'Authorization': 'Bearer ' + login.json()['token']}, tmp_path
    settings.cache_clear()


def test_admin_sessions_and_local_storage(self_hosted):
    client, headers, data_dir = self_hosted
    assert client.get('/admin/documents').status_code == 401
    session = client.post('/sessions').json()
    assert client.get('/messages', headers={'X-Session-Token': session['token']}).json() == []

    body = {
        'title': 'Admission reference', 'source_url': 'https://utc.edu.vn/test',
        'admission_year': 2026, 'campus': 'hanoi',
        'text': 'This is a sufficiently long admission reference document for indexing.'
    }
    response = client.post('/admin/documents/upload', headers=headers,
        data={'metadata': __import__('json').dumps(body)},
        files={'file': ('source.txt', body['text'].encode(), 'text/plain')})
    assert response.status_code == 200, response.text
    document_id = response.json()['id']
    row = client.get('/admin/documents', headers=headers).json()[0]
    assert row['id'] == document_id
    download = client.get(f'/admin/documents/{document_id}/download', headers=headers)
    assert download.status_code == 200
    assert download.content == body['text'].encode()
    assert (data_dir / 'utc.sqlite3').exists()
    assert client.post('/admin/logout', headers=headers).status_code == 200
    assert client.get('/admin/documents', headers=headers).status_code == 401


def test_major_and_freshman_crud(self_hosted):
    client, headers, _ = self_hosted
    major = {
        'admission_code': 'UTC123', 'major_code': '7520103',
        'name': 'Engineering', 'program_name': 'Engineering program',
        'admission_year': 2026, 'campus': 'hanoi', 'quota': 100,
        'methods': ['Exam'], 'subject_groups': ['A00'],
        'source_url': 'https://utc.edu.vn/test'
    }
    created = client.post('/admin/majors', headers=headers, json=major)
    assert created.status_code == 201, created.text
    assert client.post('/admin/majors', headers=headers, json=major).status_code == 409
    assert client.get('/majors', params={'q': 'Engineering'}).json()['total'] == 1
    major_id = created.json()['id']
    assert client.delete(f'/admin/majors/{major_id}', headers=headers).status_code == 200
    assert client.get('/majors').json()['total'] == 0

def test_local_rag_and_feedback(self_hosted, monkeypatch):
    client, headers, _ = self_hosted

    class FakeEmbeddings:
        def embed_documents(self, parts):
            return [[1.0, 0.0, 0.0] for _ in parts]

        def embed_query(self, question):
            return [1.0, 0.0, 0.0]

    monkeypatch.setattr(main, 'embeddings', lambda: FakeEmbeddings())
    monkeypatch.setattr(main, 'generate', lambda question, matches:
                        ('Answer [1]', [matches[0]], True))
    body = {
        'title': 'Admission reference', 'source_url': 'https://utc.edu.vn/test',
        'admission_year': 2026, 'campus': 'hanoi',
        'text': 'This official admission reference contains enough content to answer questions.'
    }
    created = client.post('/admin/documents', headers=headers, json=body)
    assert created.status_code == 200, created.text
    docs = client.get('/admin/documents', headers=headers).json()
    assert docs[0]['status'] == 'ready'
    session = client.post('/sessions').json()
    session_headers = {'X-Session-Token': session['token']}
    answer = client.post('/chat', headers=session_headers,
                         json={'question': 'What is the admission reference?',
                               'year': 2026, 'campus': 'hanoi'})
    assert answer.status_code == 200, answer.text
    assert answer.json()['content'] == 'Answer [1]'
    assert len(answer.json()['sources']) == 1
    rating = client.post('/feedback', headers=session_headers,
                         json={'message_id': answer.json()['id'], 'rating': 1})
    assert rating.status_code == 200, rating.text
    rating_again = client.post('/feedback', headers=session_headers,
                               json={'message_id': answer.json()['id'], 'rating': -1})
    assert rating_again.status_code == 200, rating_again.text
    assert rating_again.json()['rating'] == -1
    assert len(client.get('/messages', headers=session_headers).json()) == 2
