from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from app import main, rag

@pytest.fixture
def client():
    main.rates.clear()
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()

def test_health(client):
    assert client.get('/health').status_code == 200

def test_admin_requires_login(client):
    assert client.get('/admin/documents').status_code == 401

def test_history_requires_session(client):
    assert client.get('/messages').status_code == 401

def test_user_metadata_cannot_grant_admin(client, monkeypatch):
    fake = MagicMock()
    fake.auth.get_user.return_value.user = SimpleNamespace(id='user', app_metadata={}, user_metadata={'role': 'admin'})
    monkeypatch.setattr(main, 'db', lambda: fake)
    assert client.get('/admin/documents', headers={'Authorization': 'Bearer test'}).status_code == 403

@pytest.mark.parametrize('url', ['http://utc.edu.vn', 'https://localhost/a', 'https://utc.edu.vn.evil.com', 'https://user@utc.edu.vn', 'https://utc.edu.vn:444/a', 'file:///etc/passwd'])
def test_reject_untrusted_urls(url):
    with pytest.raises(ValueError):
        rag.valid_url(url)

def test_filters():
    assert rag.filters('Học phí năm 2025 tại TP.HCM?', 2026, 'hanoi') == (2025, 'hcm')
    assert rag.filters('Xét tuyển Hà Nội', 2026, 'hcm') == (2026, 'hanoi')

def test_ambiguous_filters():
    with pytest.raises(ValueError):
        rag.filters('So sánh 2025 với 2026', 2026, 'hanoi')
    with pytest.raises(ValueError):
        rag.filters('Hà Nội và HCM', 2026, 'hanoi')

def test_invalid_file():
    with pytest.raises(ValueError):
        rag.extract(b'not a pdf', 'test.pdf')
    with pytest.raises(ValueError):
        rag.extract(b'hello', 'test.exe')

def test_chunking():
    result = rag.chunks('Thông tin tuyển sinh Đại học Giao thông Vận tải. ' * 100)
    assert len(result) > 1
    assert all(len(c) <= 1200 for c in result)
    assert 'tuyển sinh' in result[0]

def test_no_sources_skips_generation(client, monkeypatch):
    main.app.dependency_overrides[main.session] = lambda: 'session'
    fake = MagicMock()
    fake.rpc.return_value.execute.return_value.data = []
    fake.table.return_value.insert.return_value.execute.return_value.data = [{'role': 'assistant', 'content': rag.NO_ANSWER, 'supported': False}]
    monkeypatch.setattr(main, 'db', lambda: fake)
    monkeypatch.setattr(main, 'settings', lambda: SimpleNamespace(google_api_key='test', similarity_threshold=.65))
    monkeypatch.setattr(main, 'embeddings', lambda: SimpleNamespace(embed_query=lambda q: [0.0]*768))
    generate = MagicMock(side_effect=AssertionError('Must not generate without sources'))
    monkeypatch.setattr(main, 'generate', generate)
    response = client.post('/chat', json={'question': 'Học phí?', 'year': 2026, 'campus': 'hanoi'})
    assert response.status_code == 200
    assert response.json()['supported'] is False
    generate.assert_not_called()

def test_feedback_ownership(client, monkeypatch):
    main.app.dependency_overrides[main.session] = lambda: 'own-session'
    fake = MagicMock()
    fake.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    monkeypatch.setattr(main, 'db', lambda: fake)
    assert client.post('/feedback', json={'message_id': '00000000-0000-0000-0000-000000000001', 'rating': 1}).status_code == 404

def test_rate_limit(client):
    main.app.dependency_overrides[main.session] = lambda: 'session'
    for _ in range(20):
        client.post('/chat', json={'question': ''})
    assert client.post('/chat', json={'question': ''}).status_code == 429

def test_invalid_citations(monkeypatch):
    fake = MagicMock()
    fake.with_structured_output.return_value.invoke.return_value = rag.GroundedAnswer(answer='Invented', source_ids=[99], supported=True)
    monkeypatch.setattr(rag, 'ChatGoogleGenerativeAI', lambda **kwargs: fake)
    sources = [{'title':'Source','admission_year':2026,'campus':'hanoi','content':'Text'}]
    assert rag.generate('Question', sources) == (rag.NO_ANSWER, [], False)

from google.genai.errors import ClientError, ServerError
from langchain_google_genai.chat_models import GoogleAPIError

def test_gemini_retries_then_succeeds(monkeypatch):
    chain = MagicMock()
    chain.invoke.side_effect = [ServerError(503, {'error': {'message': 'busy'}}), 'ok']
    sleep = MagicMock()
    monkeypatch.setattr(rag.time, 'sleep', sleep)
    assert rag.invoke_gemini(chain, []) == 'ok'
    assert chain.invoke.call_count == 2
    assert 1 <= sleep.call_args.args[0] <= 1.5

def test_gemini_retries_are_bounded(monkeypatch):
    chain = MagicMock()
    chain.invoke.side_effect = GoogleAPIError(503, {'error': {'message': 'busy'}})
    sleep = MagicMock()
    monkeypatch.setattr(rag.time, 'sleep', sleep)
    with pytest.raises(GoogleAPIError):
        rag.invoke_gemini(chain, [])
    assert chain.invoke.call_count == 3
    assert sleep.call_count == 2

@pytest.mark.parametrize('code', [400, 401, 403, 404])
def test_gemini_does_not_retry_configuration_errors(monkeypatch, code):
    chain = MagicMock()
    chain.invoke.side_effect = ClientError(code, {'error': {'message': 'private detail'}})
    sleep = MagicMock()
    monkeypatch.setattr(rag.time, 'sleep', sleep)
    with pytest.raises(ClientError):
        rag.invoke_gemini(chain, [])
    assert chain.invoke.call_count == 1
    sleep.assert_not_called()

@pytest.mark.parametrize('code,status', [(503,503),(429,503),(403,502)])
def test_gemini_error_is_handled_with_cors(client, monkeypatch, code, status):
    main.app.dependency_overrides[main.session] = lambda: 'session'
    fake = MagicMock()
    fake.rpc.return_value.execute.return_value.data = [{'content': 'source'}]
    monkeypatch.setattr(main, 'db', lambda: fake)
    monkeypatch.setattr(main, 'settings', lambda: SimpleNamespace(google_api_key='test', similarity_threshold=.65))
    monkeypatch.setattr(main, 'embeddings', lambda: SimpleNamespace(embed_query=lambda q: [0.0]*768))
    error = GoogleAPIError(code, {'error': {'message': 'private-key-or-provider-detail'}})
    monkeypatch.setattr(main, 'generate', MagicMock(side_effect=error))
    origin = main.app.user_middleware[0].kwargs['allow_origins'][0]
    response = client.post('/chat', json={'question': 'Test question'}, headers={'Origin': origin})
    assert response.status_code == status
    assert response.headers['access-control-allow-origin'] == origin
    assert 'private-key' not in response.text
    if status == 503:
        assert response.headers['retry-after'] == '30'
    fake.table.assert_not_called()

@pytest.mark.parametrize('field,value', [
    ('title', '  '), ('title', 'x' * 301), ('text', ' ' * 40),
    ('text', 'short'), ('admission_year', 1999), ('admission_year', None),
    ('campus', 'other'),
])
def test_document_validation_identifies_field(client, monkeypatch, field, value):
    main.app.dependency_overrides[main.admin] = lambda: 'admin'
    fake = MagicMock()
    monkeypatch.setattr(main, 'db', lambda: fake)
    body = dict(title='Valid title', source_url='https://tuyensinh.utc.edu.vn/',
                admission_year=2026, campus='hanoi', text='Private document content ' * 4)
    body[field] = value
    response = client.post('/admin/documents', json=body)
    assert response.status_code == 422
    assert response.json()['detail'][0]['loc'][-1] == field
    assert 'input' not in response.json()['detail'][0]
    assert 'Private document content' not in response.text
    fake.table.assert_not_called()

def test_document_url_rejection_is_explained(client, monkeypatch):
    main.app.dependency_overrides[main.admin] = lambda: 'admin'
    fake = MagicMock()
    monkeypatch.setattr(main, 'db', lambda: fake)
    response = client.post('/admin/documents', json=dict(
        title='Valid title', source_url='https://example.com/',
        admission_year=2026, campus='hanoi', text='Document content ' * 4))
    assert response.status_code == 422
    assert isinstance(response.json()['detail'], str)
    fake.table.assert_not_called()

def test_document_fields_trimmed():
    body = main.DocumentInput(title='  Valid title  ', source_url=' https://utc.edu.vn/ ',
                              admission_year=2026, campus='hanoi', text=' Content ' * 10)
    assert body.title == 'Valid title'
    assert body.source_url == 'https://utc.edu.vn/'
    assert body.text == body.text.strip()

import json
from fastapi import BackgroundTasks
from uuid import UUID

def test_chat_insert_has_no_null_sources(client, monkeypatch):
    main.app.dependency_overrides[main.session] = lambda: 'session'
    fake = MagicMock()
    fake.rpc.return_value.execute.return_value.data = []
    fake.table.return_value.insert.return_value.execute.return_value.data = [{'role':'assistant'}]
    monkeypatch.setattr(main,'db',lambda:fake)
    monkeypatch.setattr(main,'settings',lambda:SimpleNamespace(google_api_key='test',similarity_threshold=.65))
    monkeypatch.setattr(main,'embeddings',lambda:SimpleNamespace(embed_query=lambda q:[0.0]*768))
    assert client.post('/chat',json={'question':'Test question'}).status_code == 200
    rows = fake.table.return_value.insert.call_args.args[0]
    assert rows[0]['sources'] == []
    assert set(rows[0]) == set(rows[1])

def test_storage_requires_admin(client):
    assert client.get('/admin/documents/00000000-0000-0000-0000-000000000001/download').status_code == 401

def test_upload_preserves_original(client, monkeypatch):
    main.app.dependency_overrides[main.admin] = lambda:'admin'
    fake = MagicMock()
    fake.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    fake.table.return_value.insert.return_value.execute.return_value.data = [{'id':'doc','status':'processing'}]
    monkeypatch.setattr(main,'db',lambda:fake)
    monkeypatch.setattr(main,'ingest',MagicMock())
    content = b'Original admission document for upload test.'
    body = dict(title='Test document',source_url='https://utc.edu.vn/',admission_year=2026,campus='hanoi',text='Edited preview content for indexing test.')
    response = client.post('/admin/documents/upload', data={'metadata':json.dumps(body)},files={'file':('test.txt',content,'text/plain')})
    assert response.status_code == 200
    upload = fake.storage.from_.return_value.upload.call_args
    assert upload.args[1] == content
    assert upload.args[0].endswith('/original.txt')
    values = fake.table.return_value.insert.call_args.args[0]
    assert values['original_filename'] == 'test.txt'
    assert values['raw_text'] == body['text']

def test_storage_cleanup_on_insert_failure(monkeypatch):
    fake=MagicMock()
    fake.table.return_value.select.return_value.eq.return_value.execute.return_value.data=[]
    fake.table.return_value.insert.return_value.execute.side_effect=RuntimeError('db failed')
    monkeypatch.setattr(main,'db',lambda:fake)
    body=main.DocumentInput(title='Test document',source_url='https://utc.edu.vn/',admission_year=2026,campus='hanoi',text='Document content '*5)
    with pytest.raises(RuntimeError):
        main.persist_document(body,BackgroundTasks(),'admin',(b'original','test.txt','text/plain'))
    path=fake.storage.from_.return_value.upload.call_args.args[0]
    fake.storage.from_.return_value.remove.assert_called_once_with([path])

def test_signed_download_expires(monkeypatch):
    fake=MagicMock()
    fake.table.return_value.select.return_value.eq.return_value.execute.return_value.data=[{'storage_path':'doc/original.txt','original_filename':'test.txt','status':'ready'}]
    fake.storage.from_.return_value.create_signed_url.return_value={'signedURL':'https://example.com/signed'}
    monkeypatch.setattr(main,'db',lambda:fake)
    result=main.download_document(UUID(int=1),'admin')
    assert result['expires_in']==60
    fake.storage.from_.return_value.create_signed_url.assert_called_once_with('doc/original.txt',60,{'download':'test.txt'})

def test_storage_failure_keeps_deletion_retryable(monkeypatch):
    fake=MagicMock()
    fake.table.return_value.update.return_value.eq.return_value.in_.return_value.execute.return_value.data=[{'storage_path':'doc/original.txt'}]
    fake.storage.from_.return_value.remove.side_effect=RuntimeError('storage unavailable')
    monkeypatch.setattr(main,'db',lambda:fake)
    with pytest.raises(RuntimeError):
        main.delete_document(UUID(int=1),'admin')
    fake.table.return_value.delete.assert_not_called()
