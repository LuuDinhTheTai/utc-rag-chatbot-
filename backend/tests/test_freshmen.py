from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app
from app.freshmen import make_router

GUIDE = {'id': '00000000-0000-0000-0000-000000000001', 'cohort': 'K67',
         'admission_year': 2026, 'title': 'Freshman guide',
         'storage_path': 'freshmen/K67/source.pdf', 'is_published': True}
ITEM = {'id': '00000000-0000-0000-0000-000000000002', 'code': '01',
        'category': 'document', 'title': 'Application file',
        'applies_to': '', 'evidence': '', 'source_page': 1,
        'sort_order': 1, 'is_active': True}
BODY = {key: ITEM[key] for key in ('code', 'category', 'title', 'applies_to',
                                  'evidence', 'source_page', 'sort_order', 'is_active')}


def make_client():
    fake = MagicMock()
    query = MagicMock()
    for name in ('select', 'eq', 'order', 'limit', 'insert', 'update', 'delete'):
        getattr(query, name).return_value = query
    fake.table.return_value = query
    query.execute.side_effect = [
        SimpleNamespace(data=[GUIDE]), SimpleNamespace(data=[ITEM])
    ]
    fake.storage.from_.return_value.download.return_value = b'%PDF-example'
    test_app = FastAPI()
    test_app.include_router(make_router(lambda: fake, lambda: 'admin'))
    return TestClient(test_app), fake, query


def test_public_guide_filters_hidden_and_storage_path():
    client, _, query = make_client()
    result = client.get('/freshmen/K67')
    assert result.status_code == 200
    assert 'storage_path' not in result.json()['guide']
    query.eq.assert_any_call('is_published', True)
    query.eq.assert_any_call('is_active', True)


def test_public_pdf_uses_private_storage():
    client, fake, _ = make_client()
    result = client.get('/freshmen/K67/pdf')
    assert result.status_code == 200
    assert result.content == b'%PDF-example'
    assert result.headers['content-type'] == 'application/pdf'
    fake.storage.from_.assert_called_with('admission-documents')
    fake.storage.from_.return_value.download.assert_called_with(GUIDE['storage_path'])


def test_admin_routes_require_auth():
    with TestClient(app) as client:
        for method, path in [('get', '/admin/freshmen'),
                             ('post', '/admin/freshmen/K67/items'),
                             ('patch', '/admin/freshmen/K67/items/' + ITEM['id']),
                             ('delete', '/admin/freshmen/K67/items/' + ITEM['id'])]:
            assert client.request(method, path, json=BODY).status_code == 401


def test_create_item_uses_guide_foreign_key():
    client, _, query = make_client()
    result = client.post('/admin/freshmen/K67/items', json=BODY)
    assert result.status_code == 201
    assert query.insert.call_args.args[0]['guide_id'] == GUIDE['id']


def test_update_item_scoped_to_guide():
    client, _, query = make_client()
    result = client.patch('/admin/freshmen/K67/items/' + ITEM['id'], json=BODY)
    assert result.status_code == 200
    query.eq.assert_any_call('guide_id', GUIDE['id'])
    query.eq.assert_any_call('id', ITEM['id'])


def test_bad_item_rejected_before_database():
    client, fake, _ = make_client()
    result = client.post('/admin/freshmen/K67/items', json={**BODY, 'source_page': 0})
    assert result.status_code == 422
    fake.table.assert_not_called()


def test_bad_guide_title_is_422():
    client, fake, _ = make_client()
    result = client.post('/admin/freshmen', data={'cohort': 'K68', 'title': 'x',
                                                    'admission_year': 2026},
                         files={'file': ('x.pdf', b'%PDF-example', 'application/pdf')})
    assert result.status_code == 422
    fake.storage.from_.assert_not_called()


def test_bad_pdf_is_422_before_upload():
    client, fake, _ = make_client()
    result = client.post('/admin/freshmen', data={'cohort': 'K68',
                                                  'title': 'Valid title',
                                                  'admission_year': 2026},
                         files={'file': ('x.pdf', b'not a pdf', 'application/pdf')})
    assert result.status_code == 422
    fake.storage.from_.assert_not_called()
