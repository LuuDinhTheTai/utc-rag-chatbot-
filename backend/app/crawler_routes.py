"""One-click UTC crawler jobs with persisted status and a single active job."""
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import admin, can_edit
from .config import settings
from .localdb import connect, now
from .utc_crawler import canonical, crawl, publish, crawler_duplicate, record_duplicate

router = APIRouter(prefix='/admin/crawler/utc', tags=['UTC crawler'])
log = logging.getLogger('utc')


class CrawlInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    year: int = Field(default_factory=lambda: settings().default_year, ge=2000, le=2100)
    ocr: bool = False
    recheck_existing: bool = False


def expire_jobs(conn):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    conn.execute("UPDATE utc_crawl_jobs SET status='failed',error=?,updated_at=? "
                 "WHERE status='running' AND updated_at<?",
                 ('Lượt lấy dữ liệu bị gián đoạn. Bạn có thể chạy lại.', now(), cutoff))


def job_result(row):
    return {'id': row['id'], 'status': row['status'], 'created_at': row['created_at'],
            'updated_at': row['updated_at'], 'config': json.loads(row['config']),
            'report': json.loads(row['report']) if row['report'] else None, 'error': row['error']}


@router.get('')
def latest_job(uid=Depends(admin)):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        expire_jobs(conn)
        row = conn.execute('SELECT * FROM utc_crawl_jobs ORDER BY created_at DESC LIMIT 1').fetchone()
    return job_result(row) if row else None


@router.post('', status_code=202)
def start_job(body: CrawlInput, tasks: BackgroundTasks, uid=Depends(can_edit)):
    if body.ocr and not settings().google_api_key:
        raise HTTPException(503, 'Máy chủ chưa cấu hình khóa Gemini để đọc ảnh/PDF scan.')
    identifier, stamp = str(uuid4()), now()
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        expire_jobs(conn)
        if conn.execute("SELECT 1 FROM utc_crawl_jobs WHERE status='running'").fetchone():
            raise HTTPException(409, 'Đang có lượt lấy dữ liệu UTC. Vui lòng chờ hoàn tất.')
        conn.execute('INSERT INTO utc_crawl_jobs VALUES (?,?,?,?,?,?,?)',
                     (identifier, 'running', stamp, stamp, body.model_dump_json(), None, None))
        row = conn.execute('SELECT * FROM utc_crawl_jobs WHERE id=?', (identifier,)).fetchone()
    tasks.add_task(execute_job, identifier, body.year, body.ocr, body.recheck_existing)
    return job_result(row)


@router.post('/{identifier}/stop', status_code=202)
def stop_job(identifier: str, uid=Depends(can_edit)):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        expire_jobs(conn)
        row = conn.execute('SELECT * FROM utc_crawl_jobs WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise HTTPException(404, 'Không tìm thấy lượt lấy dữ liệu.')
        if row['status'] == 'running':
            config = json.loads(row['config'])
            config['stop_requested'] = True
            conn.execute('UPDATE utc_crawl_jobs SET config=? WHERE id=?',
                         (json.dumps(config), identifier))
            row = conn.execute('SELECT * FROM utc_crawl_jobs WHERE id=?', (identifier,)).fetchone()
    return job_result(row)


def execute_job(identifier, year, ocr, recheck_existing=False):
    stopped = threading.Event()

    def should_stop():
        with connect() as conn:
            row = conn.execute('SELECT status,config FROM utc_crawl_jobs WHERE id=?', (identifier,)).fetchone()
        return not row or row['status'] != 'running' or json.loads(row['config']).get('stop_requested', False)

    def heartbeat():
        while not stopped.wait(20):
            try:
                with connect() as conn:
                    conn.execute("UPDATE utc_crawl_jobs SET updated_at=? WHERE id=? AND status='running'", (now(), identifier))
            except Exception:
                log.warning('crawler_heartbeat_failed job=%s', identifier)

    def progress(report):
        with connect() as conn:
            conn.execute("UPDATE utc_crawl_jobs SET updated_at=?,report=? WHERE id=? AND status='running'",
                         (now(), json.dumps(report, ensure_ascii=False), identifier))

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        report = crawl(year=year, ocr=ocr, do_publish=False, progress=progress,
                       recheck_existing=recheck_existing, should_stop=should_stop)
        with connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT config FROM utc_crawl_jobs WHERE id=?', (identifier,)).fetchone()
            status = 'stopped' if row and json.loads(row['config']).get('stop_requested') else (
                'completed_with_errors' if report['errors'] else 'completed')
            conn.execute("UPDATE utc_crawl_jobs SET status=?,updated_at=?,report=? WHERE id=? AND status='running'",
                         (status, now(),
                          json.dumps(report, ensure_ascii=False), identifier))
    except Exception as exc:
        log.error('crawler_job_failed job=%s type=%s', identifier, type(exc).__name__)
        with connect() as conn:
            conn.execute("UPDATE utc_crawl_jobs SET status='failed',updated_at=?,error=? WHERE id=? AND status='running'",
                         (now(), 'Không hoàn tất được lượt lấy dữ liệu. Kiểm tra nhật ký máy chủ rồi chạy lại.', identifier))
    finally:
        stopped.set()
        thread.join(timeout=2)


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=300)
    text: str = Field(min_length=30, max_length=2_000_000)
    year: int = Field(ge=2000, le=2100)
    campus: Literal['hanoi', 'hcm']
    confirmed: Literal[True]


def expire_reviews(conn):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    conn.execute("UPDATE utc_crawl_items SET status='review',error=? "
                 "WHERE status='approving' AND review_started_at<?",
                 ('Lập chỉ mục bị gián đoạn. Kiểm tra tài liệu rồi thử duyệt lại.', cutoff))


def item_result(row, detail=False):
    original = json.loads(row['payload'])
    item = json.loads(row['review_payload']) if row['review_payload'] else original
    result = {'id': row['hash'], 'url': row['url'], 'status': row['status'],
              'seen_at': row['seen_at'], 'document_id': row['document_id'], 'error': row['error'],
              'title': item['title'], 'year': item.get('year'), 'campus': item.get('campus'),
              'duplicate': item.get('duplicate'),
              'reasons': original.get('reasons', []), 'preview': item['text'][:180]}
    if detail:
        result.update(text=item['text'], original_text=original['text'], assets=original.get('assets', []),
                      reviewed_by=row['reviewed_by'], reviewed_at=row['reviewed_at'])
    return result


@router.get('/items')
def review_items(state: Literal['pending', 'published', 'rejected', 'all'] = 'pending',
                 page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=50),
                 uid=Depends(admin)):
    conditions = {'pending': "i.status IN ('review','staged','approving')",
                  'published': "i.status IN ('published','unchanged')", 'rejected': "i.status='rejected'", 'all': '1=1'}
    # Only show the most recently observed version of each source URL.
    where = conditions[state] + ' AND NOT EXISTS (SELECT 1 FROM utc_crawl_items newer WHERE newer.url=i.url '
    where += 'AND (newer.seen_at>i.seen_at OR (newer.seen_at=i.seen_at AND newer.rowid>i.rowid)))'
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        expire_reviews(conn)
        total = conn.execute('SELECT count(*) FROM utc_crawl_items i WHERE ' + where).fetchone()[0]
        rows = conn.execute('SELECT i.* FROM utc_crawl_items i WHERE ' + where +
                            ' ORDER BY i.seen_at DESC LIMIT ? OFFSET ?', (page_size, (page-1)*page_size)).fetchall()
    return {'items': [item_result(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/items/{digest}')
def review_detail(digest: str, uid=Depends(admin)):
    with connect() as conn:
        expire_reviews(conn)
        row = conn.execute('SELECT * FROM utc_crawl_items WHERE hash=?', (digest,)).fetchone()
        if not row:
            raise HTTPException(404, 'Không tìm thấy bài đã thu thập.')
        result = item_result(row, detail=True)
        if row['status'] in {'staged', 'review', 'rejected'}:
            item = json.loads(row['review_payload'] or row['payload'])
            result['duplicate'] = crawler_duplicate(conn, item)
    return result


@router.post('/items/{digest}/reject')
def reject_item(digest: str, uid=Depends(can_edit)):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT status FROM utc_crawl_items WHERE hash=?', (digest,)).fetchone()
        if not row:
            raise HTTPException(404, 'Không tìm thấy bài đã thu thập.')
        if row['status'] not in {'staged', 'review', 'rejected'}:
            raise HTTPException(409, 'Bài đang lập chỉ mục hoặc đã được duyệt vào RAG.')
        conn.execute("UPDATE utc_crawl_items SET status='rejected',reviewed_by=?,reviewed_at=? WHERE hash=?", (uid, now(), digest))
    return {'status': 'rejected'}


@router.post('/items/{digest}/approve', status_code=202)
def approve_item(digest: str, body: ApprovalInput, tasks: BackgroundTasks, uid=Depends(can_edit)):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        expire_reviews(conn)
        row = conn.execute('SELECT * FROM utc_crawl_items WHERE hash=?', (digest,)).fetchone()
        if not row:
            raise HTTPException(404, 'Không tìm thấy bài đã thu thập.')
        if row['status'] not in {'staged', 'review', 'rejected'}:
            raise HTTPException(409, 'Bài đang lập chỉ mục hoặc đã được duyệt vào RAG.')
        if conn.execute("SELECT 1 FROM utc_crawl_items WHERE url=? AND status='approving'", (row['url'],)).fetchone():
            raise HTTPException(409, 'Một phiên bản khác của bài đang được lập chỉ mục.')
        original = json.loads(row['payload'])
        canonical(row['url'])  # Validate scope while preserving the staging identity.
        item = original | body.model_dump(exclude={'confirmed'}) | {'url': row['url'], 'reasons': []}
        duplicate = crawler_duplicate(conn, item)
        if duplicate:
            if duplicate['status'] != 'ready':
                raise HTTPException(409, f'Trùng với tài liệu “{duplicate["title"]}” đang ẩn, xử lý hoặc có lỗi. Kiểm tra tài liệu hiện có trước khi duyệt lại.')
            record_duplicate(conn, item, digest, duplicate, replace_previous=False)
            conn.execute('UPDATE utc_crawl_items SET reviewed_by=?,reviewed_at=? WHERE hash=?', (uid, now(), digest))
            return {'status': 'unchanged', 'duplicate': duplicate, 'document_id': duplicate['id']}
        if not settings().google_api_key:
            raise HTTPException(503, 'Máy chủ chưa cấu hình khóa Gemini để lập chỉ mục tài liệu.')
        conn.execute("UPDATE utc_crawl_items SET status='approving',review_payload=?,reviewed_by=?,reviewed_at=?,"
                     'review_started_at=?,error=NULL WHERE hash=?',
                     (json.dumps(item, ensure_ascii=False), uid, now(), now(), digest))
    tasks.add_task(publish_review, digest, item)
    return {'status': 'approving'}


def publish_review(digest, item):
    stopped = threading.Event()
    def heartbeat():
        while not stopped.wait(20):
            try:
                with connect() as conn:
                    conn.execute("UPDATE utc_crawl_items SET review_started_at=? WHERE hash=? AND status='approving'", (now(), digest))
            except Exception:
                log.warning('review_heartbeat_failed')
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        result = publish(item, digest)
        if result == 'existing_inactive_or_failed':
            return  # Keep the specific duplicate explanation set by publish().
        if result not in {'published', 'unchanged'}:
            raise ValueError('Document is inactive or failed')
        with connect() as conn:
            conn.execute('UPDATE utc_crawl_items SET status=?,error=NULL WHERE hash=?', (result, digest))
    except Exception as exc:
        log.error('review_publish_failed type=%s', type(exc).__name__)
        with connect() as conn:
            conn.execute("UPDATE utc_crawl_items SET status='review',error=? WHERE hash=?",
                         ('Chưa lập chỉ mục được. Nội dung đã sửa được giữ lại; kiểm tra cấu hình Gemini rồi duyệt lại.', digest))
    finally:
        stopped.set()
        thread.join(timeout=2)
