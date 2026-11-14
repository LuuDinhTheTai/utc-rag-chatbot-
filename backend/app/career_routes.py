"""Career API routes with authentication."""
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from .career_models import (
    CareerIngestRequest,
    CareerIngestResponse,
    CareerIngestSummary,
    CareerJobResult,
)
from .career_storage import (
    batch_ingest_jobs,
    BusinessError,
    DatabaseError,
    get_career_jobs,
    get_career_job_by_id,
    count_career_jobs,
)
from .localdb import connect
from .security import check_password

log = logging.getLogger('career')
router = APIRouter(prefix='/api/v1/career', tags=['Career API'])


# ============================================================================
# AUTHENTICATION
# ============================================================================

async def verify_api_key(
    request: Request,
    x_api_key: Annotated[str, Header(description='API Key')],
    x_api_secret: Annotated[str, Header(description='API Secret')]
) -> str:
    """
    Verify API credentials (V5 security model).

    Returns:
        api_key_id: For audit logging

    Raises:
        HTTPException: 401 (invalid credentials) or 403 (expired/inactive)

    Security:
        - key_hash safe to log
        - api_secret NEVER logged
        - Constant-time comparison via check_password()
    """

    # Hash the provided key (safe to log)
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()

    try:
        with connect() as conn:
            row = conn.execute(
                '''SELECT id, secret_hash, permissions, is_active, expires_at
                   FROM api_keys
                   WHERE key_hash = ?''',
                (key_hash,)
            ).fetchone()

            if not row:
                log.warning('api_key_not_found key_hash=%s ip=%s',
                           key_hash[:16], request.client.host if request.client else 'unknown')
                raise HTTPException(401, 'Invalid credentials')

            if not row['is_active']:
                log.warning('api_key_inactive key_id=%s ip=%s',
                           row['id'], request.client.host if request.client else 'unknown')
                raise HTTPException(403, 'API key is disabled')

            # Check expiry
            if row['expires_at']:
                try:
                    expiry_utc = datetime.fromisoformat(row['expires_at'])
                    now_utc = datetime.now(timezone.utc)

                    if now_utc >= expiry_utc:
                        log.warning('api_key_expired key_id=%s ip=%s',
                                   row['id'], request.client.host if request.client else 'unknown')
                        raise HTTPException(403, 'API key has expired')
                except (ValueError, TypeError) as exc:
                    log.error('api_key_invalid_expiry key_id=%s error=%s', row['id'], exc)
                    raise HTTPException(500, 'Internal server error')

            # Verify secret (constant-time comparison)
            # NEVER log x_api_secret!
            if not check_password(x_api_secret, row['secret_hash']):
                log.warning('api_secret_invalid key_id=%s ip=%s',
                           row['id'], request.client.host if request.client else 'unknown')
                raise HTTPException(401, 'Invalid credentials')

            # Check permissions
            try:
                permissions = json.loads(row['permissions'])
            except (json.JSONDecodeError, TypeError):
                log.error('api_key_invalid_permissions key_id=%s', row['id'])
                raise HTTPException(500, 'Internal server error')

            if 'career:ingest' not in permissions:
                log.warning('insufficient_permissions key_id=%s permissions=%s ip=%s',
                           row['id'], permissions, request.client.host if request.client else 'unknown')
                raise HTTPException(403, 'Insufficient permissions')

            # Update last_used_at
            conn.execute(
                'UPDATE api_keys SET last_used_at = ? WHERE id = ?',
                (datetime.now(timezone.utc).isoformat(), row['id'])
            )

            log.info('api_auth_success key_id=%s ip=%s',
                    row['id'], request.client.host if request.client else 'unknown')

            return row['id']

    except HTTPException:
        raise
    except Exception as exc:
        log.error('api_auth_error error=%s', type(exc).__name__)
        raise HTTPException(500, 'Internal server error')


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post('/ingest', response_model=CareerIngestResponse)
async def ingest_career_jobs(
    body: CareerIngestRequest,
    api_key_id: str = Depends(verify_api_key)
) -> CareerIngestResponse:
    """
    Batch ingest career jobs.

    Authentication:
        Requires X-API-Key and X-API-Secret headers
        API key must have 'career:ingest' permission

    Request:
        {
            "jobs": [
                {
                    "source": "topcv",
                    "externalId": "job-123",
                    "type": "job",
                    "title": "Backend Developer",
                    "url": "https://...",
                    "company": {"name": "...", "url": "..."},
                    "salary": {...},
                    "location": {...},
                    "experience": {...},
                    "tags": ["Python"],
                    "remainingTags": null,
                    "published": {...}
                }
            ]
        }

    Response:
        {
            "received": 1,
            "results": [
                {
                    "source": "topcv",
                    "externalId": "job-123",
                    "status": "created",  // or "updated", "unchanged", "rejected"
                    "jobId": "uuid-here",
                    "message": null
                }
            ],
            "summary": {
                "created": 1,
                "updated": 0,
                "unchanged": 0,
                "rejected": 0
            }
        }

    Status codes:
        200: Batch processed (check individual results for job status)
        401: Invalid credentials
        403: API key disabled/expired or insufficient permissions
        422: Validation error
        503: Database temporarily unavailable
        500: Internal server error
    """

    log.info('ingest_request_received api_key=%s jobs=%d',
            api_key_id, len(body.jobs))

    try:
        # Convert Pydantic models to dicts
        jobs_data = [job.model_dump(mode='json') for job in body.jobs]

        # Process batch
        result = batch_ingest_jobs(jobs_data)

        # Build response
        response = CareerIngestResponse(
            received=result['received'],
            results=[CareerJobResult(**r) for r in result['results']],
            summary=CareerIngestSummary(**result['summary'])
        )

        log.info('ingest_completed api_key=%s received=%d created=%d updated=%d unchanged=%d rejected=%d',
                api_key_id, response.received, response.summary.created,
                response.summary.updated, response.summary.unchanged, response.summary.rejected)

        return response

    except DatabaseError as exc:
        log.error('ingest_database_error api_key=%s error=%s', api_key_id, str(exc))
        raise HTTPException(
            503,
            'Database temporarily unavailable. Batch not processed. Please retry.'
        )

    except Exception as exc:
        log.error('ingest_failed api_key=%s error=%s', api_key_id, type(exc).__name__)
        raise HTTPException(500, 'Internal server error processing batch')


@router.get('/jobs')
async def list_career_jobs(
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
    api_key_id: str = Depends(verify_api_key)
):
    """
    List career jobs (for debugging/admin).

    Query params:
        source: Filter by source (optional)
        limit: Max results (default 100, max 1000)
        offset: Pagination offset (default 0)

    Returns:
        {
            "total": int,
            "jobs": [...]
        }
    """

    if limit > 1000:
        limit = 1000
    if offset < 0:
        offset = 0

    try:
        jobs = get_career_jobs(source=source, limit=limit, offset=offset)
        total = count_career_jobs(source=source)

        return {
            'total': total,
            'jobs': jobs,
            'limit': limit,
            'offset': offset
        }

    except Exception as exc:
        log.error('list_jobs_failed error=%s', type(exc).__name__)
        raise HTTPException(500, 'Internal server error')


@router.get('/jobs/{job_id}')
async def get_career_job(
    job_id: str,
    api_key_id: str = Depends(verify_api_key)
):
    """
    Get single career job by ID with full payload.

    Path params:
        job_id: Job UUID

    Returns:
        Job record with full payload or 404 if not found
    """

    try:
        job = get_career_job_by_id(job_id)

        if not job:
            raise HTTPException(404, 'Job not found')

        return job

    except HTTPException:
        raise
    except Exception as exc:
        log.error('get_job_failed job_id=%s error=%s', job_id, type(exc).__name__)
        raise HTTPException(500, 'Internal server error')


@router.get('/health')
async def career_api_health():
    """
    Health check endpoint (no authentication required).

    Returns:
        {
            "status": "ok",
            "service": "career-api"
        }
    """
    return {
        'status': 'ok',
        'service': 'career-api',
        'version': '1.0.0'
    }
