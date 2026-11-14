import json

import pytest
from fastapi import BackgroundTasks, HTTPException

from app import crawler_routes as routes, utc_crawler as crawler
from app.localdb import connect


def test_stop_finishes_current_article_and_assets(monkeypatch):
    job = routes.start_job(routes.CrawlInput(), BackgroundTasks(), uid='editor')
    first = crawler.ORIGIN + '/tin-tuyen-sinh/first'
    second = crawler.ORIGIN + '/tin-tuyen-sinh/second'
    asset = crawler.ORIGIN + '/image.png'
    requests = []

    class Fetcher:
        count = 0

        def __init__(self, *args, **kwargs):
            pass

        def load_robots(self):
            pass

        def request(self, url):
            requests.append(url)
            self.count += 1
            if url == first:
                routes.stop_job(job['id'], uid='editor')
                # Repeated stops are harmless and the job remains active.
                assert routes.stop_job(job['id'], uid='editor')['status'] == 'running'
                with pytest.raises(HTTPException) as exc:
                    routes.start_job(routes.CrawlInput(), BackgroundTasks(), uid='editor')
                assert exc.value.status_code == 409
            return url, 'image/png' if url == asset else 'text/html', b'data'

    monkeypatch.setattr(crawler, 'Fetcher', Fetcher)
    monkeypatch.setattr(crawler, 'discover', lambda *args: ([first, second], []))
    monkeypatch.setattr(crawler, 'parse_article', lambda data, url: {
        'url': url, 'title': 'Tuyển sinh Hà Nội 2026', 'text': 'Thông tin xét tuyển. ' * 20,
        'assets': [{'url': asset, 'kind': 'image'}],
    })
    monkeypatch.setattr(crawler, 'ocr_resource', lambda *args: 'Nội dung ảnh')
    routes.execute_job(job['id'], 2026, True)
    result = routes.latest_job(uid='admin')
    assert result['status'] == 'stopped'
    assert requests == [crawler.ORIGIN + '/', first, asset]
    assert len(result['report']['items']) == 1
    assert not result['report']['errors']
    with connect() as conn:
        saved = json.loads(conn.execute('SELECT payload FROM utc_crawl_items').fetchone()[0])
    assert 'Nội dung ảnh' in saved['text']
    assert routes.stop_job(job['id'], uid='editor')['status'] == 'stopped'
    assert routes.start_job(routes.CrawlInput(), BackgroundTasks(), uid='editor')['status'] == 'running'


def test_stop_before_worker_starts(monkeypatch):
    job = routes.start_job(routes.CrawlInput(), BackgroundTasks(), uid='editor')
    routes.stop_job(job['id'], uid='editor')
    def unexpected_request(*args, **kwargs):
        pytest.fail('Stopped job must not fetch any resource')
    monkeypatch.setattr(crawler.Fetcher, 'request', unexpected_request)
    routes.execute_job(job['id'], 2026, False)
    result = routes.latest_job(uid='admin')
    assert result['status'] == 'stopped'
    assert result['report']['requests'] == 0
    assert result['report']['items'] == []


def test_unknown_job_stop():
    with pytest.raises(HTTPException) as exc:
        routes.stop_job('missing', uid='editor')
    assert exc.value.status_code == 404
