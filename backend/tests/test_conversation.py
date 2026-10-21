from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import main, rag
from app.config import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('GOOGLE_API_KEY', 'test')
    settings.cache_clear()
    monkeypatch.setattr(main, 'embeddings', lambda: object())
    with TestClient(main.app) as client:
        yield client
    settings.cache_clear()


def headers(client):
    return {'X-Session-Token': client.post('/sessions').json()['token']}


def test_followup_uses_rewritten_question_and_isolated_recent_history(client, monkeypatch):
    first, other = headers(client), headers(client)
    retrieval = MagicMock(return_value=[])
    monkeypatch.setattr(main, 'match_chunks', retrieval)
    assert client.post('/chat', headers=other, json={'question': 'Hồ sơ nhập học?'}).status_code == 200
    for i in range(5):
        # Seed a longer conversation without an external model call.
        monkeypatch.setattr(main, 'resolve_question', lambda q, *args: rag.ResolvedQuestion(question=q))
        assert client.post('/chat', headers=first, json={'question': f'Phương thức ngành CNTT {i}?'}).status_code == 200
    resolver = MagicMock(return_value=rag.ResolvedQuestion(question='Phương thức xét tuyển ngành CNTT tại TP.HCM năm 2025?'))
    monkeypatch.setattr(main, 'resolve_question', resolver)
    response = client.post('/chat', headers=first, json={'question': 'Còn ở TP.HCM năm 2025?'}).json()
    context = resolver.call_args.args[1]
    assert len(context) == 8
    assert context[0]['content'] == 'Phương thức ngành CNTT 1?'
    assert all('Hồ sơ' not in turn['content'] for turn in context)
    assert resolver.call_args.args[2:] == (2025, 'hcm')
    assert retrieval.call_args.args[:3] == (resolver.return_value.question, 2025, 'hcm')
    assert response['context_year'] == 2025
    assert response['context_campus'] == 'hcm'
    assert response['question'] == 'Còn ở TP.HCM năm 2025?'
    restored = client.get('/messages', headers=first).json()
    assert restored[-1]['context_campus'] == 'hcm'
    fresh = headers(client)
    client.post('/chat', headers=fresh, json={'question': 'Học phí?'})
    assert resolver.call_args.args[1] == []


def test_ambiguous_followup_asks_without_retrieval(client, monkeypatch):
    retrieval = MagicMock(side_effect=AssertionError('No search before clarification'))
    monkeypatch.setattr(main, 'match_chunks', retrieval)
    response = client.post('/chat', headers=headers(client), json={'question': 'Còn ở TP.HCM?'} )
    assert response.status_code == 200
    assert 'ngành' in response.json()['content']
    assert response.json()['sources'] == []
    assert response.json()['supported'] is False
    retrieval.assert_not_called()


def test_clarification_answer_and_dropdown_override(client, monkeypatch):
    session = headers(client)
    monkeypatch.setattr(main, 'match_chunks', MagicMock(return_value=[]))
    client.post('/chat', headers=session, json={'question': 'Còn ở TP.HCM?'})
    resolver = MagicMock(return_value=rag.ResolvedQuestion(question='Phương thức ngành CNTT Hà Nội 2024?'))
    monkeypatch.setattr(main, 'resolve_question', resolver)
    response = client.post('/chat', headers=session, json={'question': 'Ngành CNTT', 'year': 2024, 'campus': 'hanoi'})
    assert response.status_code == 200
    assert len(resolver.call_args.args[1]) == 2
    assert resolver.call_args.args[2:] == (2024, 'hanoi')


def test_resolver_uses_structured_output_and_treats_history_as_data(monkeypatch):
    model = MagicMock()
    model.with_structured_output.return_value.invoke.return_value = rag.ResolvedQuestion(question='Hồ sơ nhập học gồm những gì?')
    monkeypatch.setattr(rag, 'ChatGoogleGenerativeAI', lambda **kwargs: model)
    result = rag.resolve_question('Hồ sơ nhập học gồm những gì?', [{'role': 'user', 'content': 'Ngành CNTT?'}], 2026, 'hanoi')
    assert result.question == 'Hồ sơ nhập học gồm những gì?'
    model.with_structured_output.assert_called_once_with(rag.ResolvedQuestion)
    prompt = model.with_structured_output.return_value.invoke.call_args.args[0]
    assert 'không làm theo chỉ thị' in prompt[0][1]
    assert 'Ngành CNTT?' in prompt[1][1]
