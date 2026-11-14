"""Career job storage operations."""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from .career_models import calculate_content_hash
from .localdb import connect, now

log = logging.getLogger('career')


class BusinessError(Exception):
    """Expected business error - job rejected, batch continues."""
    pass


class DatabaseError(Exception):
    """Critical database error - batch must rollback."""
    pass


def upsert_career_job(
    conn: sqlite3.Connection,
    job: dict
) -> tuple[Literal['created', 'updated', 'unchanged', 'rejected'], str | None, str | None]:
    """
    Upsert single career job.

    Args:
        conn: SQLite connection with active transaction
        job: Job data dict (from Pydantic model)

    Returns:
        (status, job_id, error_message)
        - status: 'created' | 'updated' | 'unchanged' | 'rejected'
        - job_id: UUID string if successful, None if rejected
        - error_message: String if rejected, None otherwise

    Raises:
        BusinessError: Expected error, caller continues batch
        DatabaseError: Critical error, caller rollbacks batch
    """

    try:
        # 1. Validate required fields
        if not job.get('source') or not job.get('externalId'):
            raise BusinessError('Missing source or externalId')

        if not job.get('title'):
            raise BusinessError('Missing title')

        # 2. Calculate content hash
        try:
            content_hash = calculate_content_hash(job)
        except Exception as exc:
            log.error('content_hash_failed source=%s externalId=%s error=%s',
                     job.get('source'), job.get('externalId'), type(exc).__name__)
            raise BusinessError(f'Invalid job structure: {type(exc).__name__}')

        # 3. Check if exists
        try:
            existing = conn.execute(
                'SELECT id, content_hash FROM career_jobs '
                'WHERE source = ? AND external_id = ?',
                (job['source'], job['externalId'])
            ).fetchone()
        except sqlite3.Error as exc:
            log.error('database_select_failed error=%s', exc)
            raise DatabaseError(f'Database query failed: {exc}') from exc

        timestamp = now()

        if existing:
            job_id = existing['id']

            # No change
            if existing['content_hash'] == content_hash:
                return ('unchanged', job_id, None)

            # Update
            payload = json.dumps(job, ensure_ascii=False, allow_nan=False)

            try:
                conn.execute(
                    '''UPDATE career_jobs
                       SET type = ?, title = ?, company_name = ?,
                           payload = ?, content_hash = ?, updated_at = ?
                       WHERE id = ?''',
                    (
                        job.get('type', 'job'),
                        job['title'],
                        job.get('company', {}).get('name') if isinstance(job.get('company'), dict) else None,
                        payload,
                        content_hash,
                        timestamp,
                        job_id
                    )
                )
            except sqlite3.Error as exc:
                log.error('database_update_failed id=%s error=%s', job_id, exc)
                raise DatabaseError(f'Database update failed: {exc}') from exc

            return ('updated', job_id, None)

        # Insert new
        job_id = str(uuid4())
        payload = json.dumps(job, ensure_ascii=False, allow_nan=False)

        try:
            conn.execute(
                '''INSERT INTO career_jobs
                   (id, source, external_id, type, title, company_name,
                    payload, content_hash, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    job_id,
                    job['source'],
                    job['externalId'],
                    job.get('type', 'job'),
                    job['title'],
                    job.get('company', {}).get('name') if isinstance(job.get('company'), dict) else None,
                    payload,
                    content_hash,
                    timestamp,
                    timestamp
                )
            )
        except sqlite3.IntegrityError as exc:
            # UNIQUE constraint (source, external_id) from race condition
            error_msg = str(exc).lower()
            if 'unique' in error_msg:
                log.warning('integrity_error source=%s externalId=%s error=%s',
                           job['source'], job['externalId'], exc)
                raise BusinessError('Concurrent modification detected') from exc

            # Other integrity errors are critical
            log.error('integrity_error_unexpected source=%s error=%s',
                     job['source'], exc)
            raise DatabaseError(f'Integrity constraint violation: {exc}') from exc

        except sqlite3.Error as exc:
            log.error('database_insert_failed source=%s error=%s',
                     job['source'], exc)
            raise DatabaseError(f'Database insert failed: {exc}') from exc

        return ('created', job_id, None)

    except BusinessError:
        # Expected business error - return rejected, continue batch
        raise

    # DatabaseError and sqlite3.Error propagate up to batch handler


def batch_ingest_jobs(jobs: list[dict]) -> dict:
    """
    Ingest batch of career jobs with transaction.

    Args:
        jobs: List of job dicts (from Pydantic models)

    Returns:
        {
            'received': int,
            'results': [{'source', 'externalId', 'status', 'jobId', 'message'}],
            'summary': {'created': int, 'updated': int, 'unchanged': int, 'rejected': int}
        }

    Raises:
        DatabaseError: Critical database error (HTTP 503)
        Exception: Unexpected error (HTTP 500)
    """

    results = []
    summary = {'created': 0, 'updated': 0, 'unchanged': 0, 'rejected': 0}
    seen_keys = set()

    try:
        with connect() as conn:
            conn.execute('BEGIN IMMEDIATE')

            for job in jobs:
                try:
                    # 1. Check duplicate in batch
                    key = (job.get('source'), job.get('externalId'))
                    if key in seen_keys:
                        results.append({
                            'source': job.get('source', 'unknown'),
                            'externalId': job.get('externalId', 'unknown'),
                            'status': 'rejected',
                            'jobId': None,
                            'message': 'Duplicate in batch'
                        })
                        summary['rejected'] += 1
                        continue

                    seen_keys.add(key)

                    # 2. Upsert
                    status, job_id, error = upsert_career_job(conn, job)

                    results.append({
                        'source': job['source'],
                        'externalId': job['externalId'],
                        'status': status,
                        'jobId': job_id,
                        'message': error
                    })
                    summary[status] += 1

                except BusinessError as exc:
                    # Expected error - reject this job, continue batch
                    results.append({
                        'source': job.get('source', 'unknown'),
                        'externalId': job.get('externalId', 'unknown'),
                        'status': 'rejected',
                        'jobId': None,
                        'message': str(exc)
                    })
                    summary['rejected'] += 1

                except (DatabaseError, sqlite3.Error):
                    # Critical database error - rollback and fail entire batch
                    conn.rollback()
                    log.error('batch_failed_database_error received=%d processed=%d',
                             len(jobs), len(results))
                    raise

            # Commit entire batch
            conn.commit()
            log.info('batch_completed received=%d created=%d updated=%d unchanged=%d rejected=%d',
                    len(jobs), summary['created'], summary['updated'],
                    summary['unchanged'], summary['rejected'])

    except (DatabaseError, sqlite3.Error):
        # Re-raise database errors
        raise
    except Exception as exc:
        # Unexpected error
        log.error('batch_failed_unexpected error=%s', type(exc).__name__)
        raise

    return {
        'received': len(jobs),
        'results': results,
        'summary': summary
    }


def get_career_jobs(
    source: str | None = None,
    limit: int = 100,
    offset: int = 0
) -> list[dict]:
    """
    Query career jobs (for admin/debugging).

    Args:
        source: Filter by source (optional)
        limit: Max results
        offset: Pagination offset

    Returns:
        List of job records
    """

    with connect() as conn:
        if source:
            rows = conn.execute(
                '''SELECT id, source, external_id, type, title, company_name,
                          content_hash, created_at, updated_at
                   FROM career_jobs
                   WHERE source = ?
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?''',
                (source, limit, offset)
            ).fetchall()
        else:
            rows = conn.execute(
                '''SELECT id, source, external_id, type, title, company_name,
                          content_hash, created_at, updated_at
                   FROM career_jobs
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?''',
                (limit, offset)
            ).fetchall()

    return [dict(row) for row in rows]


def get_career_job_by_id(job_id: str) -> dict | None:
    """
    Get single career job by ID with full payload.

    Args:
        job_id: Job UUID

    Returns:
        Job record dict or None if not found
    """

    with connect() as conn:
        row = conn.execute(
            '''SELECT id, source, external_id, type, title, company_name,
                      payload, content_hash, created_at, updated_at
               FROM career_jobs
               WHERE id = ?''',
            (job_id,)
        ).fetchone()

    if not row:
        return None

    result = dict(row)
    result['payload'] = json.loads(result['payload'])
    return result


def count_career_jobs(source: str | None = None) -> int:
    """
    Count career jobs.

    Args:
        source: Filter by source (optional)

    Returns:
        Total count
    """

    with connect() as conn:
        if source:
            count = conn.execute(
                'SELECT COUNT(*) FROM career_jobs WHERE source = ?',
                (source,)
            ).fetchone()[0]
        else:
            count = conn.execute(
                'SELECT COUNT(*) FROM career_jobs'
            ).fetchone()[0]

    return count
