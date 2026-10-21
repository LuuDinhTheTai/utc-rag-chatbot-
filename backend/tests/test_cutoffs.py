import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from scripts.import_cutoffs import import_cutoffs, parse_cutoffs

DATA = Path(__file__).resolve().parents[1] / 'data' / 'cutoffs_2024_2026.json'


def test_dataset_is_complete_and_sourced():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    rows = parse_cutoffs(data)
    assert len(rows) == 558
    assert {row[0] for row in rows} == {2024, 2025, 2026}
    assert {row[1] for row in rows} == {'hanoi', 'hcm'}
    assert {row[4] for row in rows} == {'PT1', 'PT2', 'PT3', 'PT4'}
    assert all(row[7].startswith('https://') for row in rows)


def test_import_and_public_filters(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    settings.cache_clear()
    try:
        rows = parse_cutoffs(json.loads(DATA.read_text(encoding='utf-8')))
        assert import_cutoffs(rows)['inserted'] == 558
        assert import_cutoffs(rows) == {'inserted': 0, 'skipped': 558, 'total': 558}
        with TestClient(app) as client:
            options = client.get('/cutoffs/options').json()
            assert options['years'] == [2026, 2025, 2024]
            assert 'Công nghệ thông tin' in options['majors']
            response = client.get('/cutoffs', params={'q': 'cong nghe thong tin', 'year': 2025, 'campus': 'hcm', 'method': 'PT1'})
            assert response.status_code == 200
            data = response.json()
            assert data['total'] >= 1
            assert all(row['admission_year'] == 2025 and row['campus'] == 'hcm' and row['method'] == 'PT1' for row in data['items'])
            assert all('Công nghệ thông tin' in row['program_name'] for row in data['items'])
            selected = client.get('/cutoffs', params={'major': 'Công nghệ thông tin', 'year': 2025, 'campus': 'hcm', 'method': 'PT1'}).json()
            assert selected['total'] >= 1
            code = selected['items'][0]['admission_code']
            linked = client.get('/cutoffs', params={'admission_code': code, 'campus': 'hcm', 'page_size': 100}).json()
            expected = [row for row in rows if row[1] == 'hcm' and row[2] == code]
            assert linked['total'] == len(expected)
            assert all(row['admission_code'] == code and row['campus'] == 'hcm' for row in linked['items'])
            assert client.get('/cutoffs', params={'admission_code': code + 'missing'}).json()['total'] == 0
            assert all(row['program_name'] == 'Công nghệ thông tin' for row in selected['items'])
            assert client.get('/cutoffs', params={'major': 'Không tồn tại'}).json()['total'] == 0
            assert client.get('/cutoffs', params={'q': '%', 'page_size': 1}).json()['total'] == 0
            assert client.get('/cutoffs', params={'page_size': 1}).json()['total'] == 558
            assert client.get('/cutoffs', params={'page_size': 101}).status_code == 422
            assert client.get('/cutoffs', params={'method': 'OTHER'}).status_code == 422
    finally:
        settings.cache_clear()


def test_import_rejects_bad_scores_and_unofficial_source():
    original = json.loads(DATA.read_text(encoding='utf-8'))
    for change in ({'score': 1300}, {'source_url': 'https://example.com/notice'}, {'scale': 31}):
        data = {'scores': [dict(original['scores'][0], **change)]}
        with pytest.raises(ValueError):
            parse_cutoffs(data)
