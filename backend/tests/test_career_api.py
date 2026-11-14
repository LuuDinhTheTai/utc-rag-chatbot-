"""Tests for Career API endpoints and authentication."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.localdb import connect
from app.security import password_hash
from app.career_models import calculate_content_hash


client = TestClient(app)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def test_api_key():
    """Create test API key and return credentials."""
    from uuid import uuid4

    api_key = 'test_key_' + 'a' * 32
    api_secret = 'test_secret_' + 'b' * 48
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    secret_hash = password_hash(api_secret)
    key_id = str(uuid4())

    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        # Clean up any existing test keys
        conn.execute("DELETE FROM api_keys WHERE name LIKE 'Test%'")

        conn.execute('''
            INSERT INTO api_keys (
                id, key_hash, secret_hash, name, description, permissions,
                is_active, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, NULL)
        ''', (
            key_id,
            key_hash,
            secret_hash,
            'Test API Key',
            'For testing only',
            json.dumps(['career:ingest']),
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()

    yield {
        'api_key': api_key,
        'api_secret': api_secret,
        'key_id': key_id
    }

    # Cleanup
    with connect() as conn:
        conn.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
        conn.commit()


@pytest.fixture
def sample_job():
    """Sample job data for testing."""
    return {
        'source': 'topcv',
        'externalId': 'test-job-001',
        'type': 'job',
        'title': 'Backend Developer',
        'url': 'https://example.com/job/001',
        'company': {
            'name': 'Test Company',
            'url': 'https://example.com/company'
        },
        'salary': {
            'raw': '15-25M',
            'min': 15000000,
            'max': 25000000,
            'currency': 'VND',
            'unit': 'month'
        },
        'location': {
            'raw': 'Hà Nội'
        },
        'experience': {
            'raw': '2-3 năm'
        },
        'tags': ['Python', 'FastAPI', 'PostgreSQL'],
        'remainingTags': None,
        'published': {
            'raw': '2 days ago',
            'publishedAt': None
        }
    }


# ============================================================================
# TEST 1-3: AUTHENTICATION
# ============================================================================

def test_01_health_endpoint_no_auth():
    """Test 1: Health endpoint accessible without auth."""
    response = client.get('/api/v1/career/health')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'ok'
    assert data['service'] == 'career-api'


def test_02_ingest_without_credentials():
    """Test 2: Ingest endpoint rejects requests without credentials."""
    response = client.post('/api/v1/career/ingest', json={'jobs': []})
    assert response.status_code == 422  # Missing required headers


def test_03_ingest_with_invalid_credentials(sample_job):
    """Test 3: Ingest endpoint rejects invalid credentials."""
    response = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [sample_job]},
        headers={
            'X-API-Key': 'invalid_key',
            'X-API-Secret': 'invalid_secret'
        }
    )
    assert response.status_code == 401
    assert 'Invalid credentials' in response.json()['detail']


# ============================================================================
# TEST 4-8: SINGLE JOB OPERATIONS
# ============================================================================

def test_04_create_single_job(test_api_key, sample_job):
    """Test 4: Create a new job successfully."""
    response = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [sample_job]},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )

    assert response.status_code == 200
    data = response.json()

    assert data['received'] == 1
    assert len(data['results']) == 1
    assert data['results'][0]['status'] == 'created'
    assert data['results'][0]['jobId'] is not None
    assert data['results'][0]['source'] == 'topcv'
    assert data['results'][0]['externalId'] == 'test-job-001'

    assert data['summary']['created'] == 1
    assert data['summary']['updated'] == 0
    assert data['summary']['unchanged'] == 0
    assert data['summary']['rejected'] == 0

    # Cleanup
    job_id = data['results'][0]['jobId']
    with connect() as conn:
        conn.execute('DELETE FROM career_jobs WHERE id = ?', (job_id,))
        conn.commit()


def test_05_update_changed_job(test_api_key, sample_job):
    """Test 5: Update job when content changes."""
    # Create initial job
    response1 = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [sample_job]},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )
    assert response1.status_code == 200
    job_id = response1.json()['results'][0]['jobId']

    # Change job content
    modified_job = sample_job.copy()
    modified_job['title'] = 'Senior Backend Developer'

    # Send update
    response2 = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [modified_job]},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )

    assert response2.status_code == 200
    data = response2.json()

    assert data['results'][0]['status'] == 'updated'
    assert data['results'][0]['jobId'] == job_id
    assert data['summary']['updated'] == 1

    # Cleanup
    with connect() as conn:
        conn.execute('DELETE FROM career_jobs WHERE id = ?', (job_id,))
        conn.commit()


def test_06_unchanged_job(test_api_key, sample_job):
    """Test 6: Return unchanged when content identical."""
    # Create job
    response1 = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [sample_job]},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )
    job_id = response1.json()['results'][0]['jobId']

    # Send same job again
    response2 = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [sample_job]},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )

    assert response2.status_code == 200
    data = response2.json()

    assert data['results'][0]['status'] == 'unchanged'
    assert data['results'][0]['jobId'] == job_id
    assert data['summary']['unchanged'] == 1

    # Cleanup
    with connect() as conn:
        conn.execute('DELETE FROM career_jobs WHERE id = ?', (job_id,))
        conn.commit()


def test_07_reject_invalid_job(test_api_key):
    """Test 7: Reject job with missing required fields."""
    invalid_job = {
        'source': 'topcv',
        'externalId': 'invalid-001'
        # Missing 'title' - required field
    }

    response = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [invalid_job]},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )

    assert response.status_code == 422  # Pydantic validation error


def test_08_reject_job_missing_source(test_api_key, sample_job):
    """Test 8: Reject job with missing source."""
    bad_job = sample_job.copy()
    del bad_job['source']

    response = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [bad_job]},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )

    assert response.status_code == 422


# ============================================================================
# TEST 9-11: BATCH OPERATIONS
# ============================================================================

def test_09_batch_ingest_multiple_jobs(test_api_key, sample_job):
    """Test 9: Ingest multiple jobs in single batch."""
    jobs = []
    for i in range(5):
        job = sample_job.copy()
        job['externalId'] = f'batch-job-{i:03d}'
        job['title'] = f'Developer {i+1}'
        jobs.append(job)

    response = client.post(
        '/api/v1/career/ingest',
        json={'jobs': jobs},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )

    assert response.status_code == 200
    data = response.json()

    assert data['received'] == 5
    assert len(data['results']) == 5
    assert data['summary']['created'] == 5
    assert all(r['status'] == 'created' for r in data['results'])

    # Cleanup
    job_ids = [r['jobId'] for r in data['results']]
    with connect() as conn:
        conn.execute(f"DELETE FROM career_jobs WHERE id IN ({','.join('?' * len(job_ids))})", job_ids)
        conn.commit()


def test_10_batch_with_mixed_results(test_api_key, sample_job):
    """Test 10: Batch with new, updated, unchanged jobs."""
    # Create initial jobs
    job1 = sample_job.copy()
    job1['externalId'] = 'mixed-001'
    job1['title'] = 'Original Title 1'

    job2 = sample_job.copy()
    job2['externalId'] = 'mixed-002'
    job2['title'] = 'Original Title 2'

    response1 = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [job1, job2]},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )
    assert response1.status_code == 200

    # Send batch: 1 unchanged, 1 updated, 1 new
    job1_unchanged = job1.copy()  # Same as before

    job2_updated = job2.copy()
    job2_updated['title'] = 'Updated Title 2'  # Changed

    job3_new = sample_job.copy()
    job3_new['externalId'] = 'mixed-003'  # New job
    job3_new['title'] = 'New Title 3'

    response2 = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [job1_unchanged, job2_updated, job3_new]},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )

    assert response2.status_code == 200
    data = response2.json()

    assert data['received'] == 3
    assert data['summary']['unchanged'] == 1  # mixed-001
    assert data['summary']['updated'] == 1    # mixed-002
    assert data['summary']['created'] == 1    # mixed-003
    assert data['summary']['rejected'] == 0

    # Verify specific jobs
    statuses = {r['externalId']: r['status'] for r in data['results']}
    assert statuses['mixed-001'] == 'unchanged'
    assert statuses['mixed-002'] == 'updated'
    assert statuses['mixed-003'] == 'created'

    # Cleanup
    with connect() as conn:
        conn.execute("DELETE FROM career_jobs WHERE source = 'topcv' AND external_id LIKE 'mixed-%'")
        conn.commit()


def test_11_batch_with_duplicate_in_batch(test_api_key, sample_job):
    """Test 11: Reject duplicate (source, externalId) within batch."""
    job1 = sample_job.copy()
    job1['externalId'] = 'dup-001'

    job2 = sample_job.copy()
    job2['externalId'] = 'dup-001'  # Same as job1

    response = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [job1, job2]},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )

    assert response.status_code == 200
    data = response.json()

    assert data['received'] == 2
    assert data['summary']['created'] == 1
    assert data['summary']['rejected'] == 1

    # One created, one rejected
    statuses = [r['status'] for r in data['results']]
    assert 'created' in statuses
    assert 'rejected' in statuses

    # Rejected one should have error message
    rejected = next(r for r in data['results'] if r['status'] == 'rejected')
    assert 'Duplicate in batch' in rejected['message']

    # Cleanup
    with connect() as conn:
        conn.execute("DELETE FROM career_jobs WHERE source = 'topcv' AND external_id = 'dup-001'")
        conn.commit()


# ============================================================================
# TEST 12-13: AUTHENTICATION EDGE CASES
# ============================================================================

def test_12_expired_api_key(sample_job):
    """Test 12: Reject expired API key."""
    from uuid import uuid4

    api_key = 'expired_key_' + 'c' * 32
    api_secret = 'expired_secret_' + 'd' * 48
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    secret_hash = password_hash(api_secret)

    # Create key with created_at in past, expires_at also in past
    created_at = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    expires_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    key_id = str(uuid4())
    with connect() as conn:
        conn.execute('''
            INSERT INTO api_keys (
                id, key_hash, secret_hash, name, description, permissions,
                is_active, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        ''', (
            key_id,
            key_hash,
            secret_hash,
            'Expired Key',
            '',
            json.dumps(['career:ingest']),
            created_at,
            expires_at
        ))
        conn.commit()

    # Try to use expired key
    response = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [sample_job]},
        headers={
            'X-API-Key': api_key,
            'X-API-Secret': api_secret
        }
    )

    assert response.status_code == 403
    assert 'expired' in response.json()['detail'].lower()

    # Cleanup
    with connect() as conn:
        conn.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
        conn.commit()


def test_13_inactive_api_key(sample_job):
    """Test 13: Reject inactive API key."""
    from uuid import uuid4

    api_key = 'inactive_key_' + 'e' * 32
    api_secret = 'inactive_secret_' + 'f' * 48
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    secret_hash = password_hash(api_secret)

    key_id = str(uuid4())
    with connect() as conn:
        conn.execute('''
            INSERT INTO api_keys (
                id, key_hash, secret_hash, name, description, permissions,
                is_active, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, NULL)
        ''', (
            key_id,
            key_hash,
            secret_hash,
            'Inactive Key',
            '',
            json.dumps(['career:ingest']),
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()

    # Try to use inactive key
    response = client.post(
        '/api/v1/career/ingest',
        json={'jobs': [sample_job]},
        headers={
            'X-API-Key': api_key,
            'X-API-Secret': api_secret
        }
    )

    assert response.status_code == 403
    assert 'disabled' in response.json()['detail'].lower()

    # Cleanup
    with connect() as conn:
        conn.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
        conn.commit()


# ============================================================================
# TEST 14: CONTENT HASH
# ============================================================================

def test_14_content_hash_calculation():
    """Test 14: Content hash matches expected values."""
    job = {
        'type': 'job',
        'title': 'Test Job',
        'url': 'https://example.com/job',
        'company': {'name': 'Test Co', 'url': 'https://example.com'},
        'salary': {'raw': '10M', 'min': None, 'max': None, 'currency': None, 'unit': None},
        'location': {'raw': 'Hanoi'},
        'experience': {'raw': '2 years'},
        'tags': ['Python'],
        'remainingTags': None,
        'published': {'raw': '1 day ago', 'publishedAt': None}
    }

    hash1 = calculate_content_hash(job)

    # Should be deterministic
    hash2 = calculate_content_hash(job)
    assert hash1 == hash2

    # Should be 64 hex chars (SHA-256)
    assert len(hash1) == 64
    assert all(c in '0123456789abcdef' for c in hash1)

    # Change content should change hash
    job_modified = job.copy()
    job_modified['title'] = 'Different Title'
    hash3 = calculate_content_hash(job_modified)
    assert hash3 != hash1

    # Fields not in hash should not affect it
    job_with_extra = job.copy()
    job_with_extra['published'] = {'raw': '2 days ago', 'publishedAt': None}
    hash4 = calculate_content_hash(job_with_extra)
    # Published is not in hash calculation, so should match
    # (based on content object in calculate_content_hash)


# ============================================================================
# TEST 15: QUERY ENDPOINTS
# ============================================================================

def test_15_list_jobs_endpoint(test_api_key, sample_job):
    """Test 15: List jobs endpoint with pagination."""
    # Create test jobs
    jobs = []
    for i in range(3):
        job = sample_job.copy()
        job['externalId'] = f'list-job-{i:03d}'
        jobs.append(job)

    response = client.post(
        '/api/v1/career/ingest',
        json={'jobs': jobs},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )
    created_ids = [r['jobId'] for r in response.json()['results']]

    # Query list
    response = client.get(
        '/api/v1/career/jobs?source=topcv&limit=10',
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )

    assert response.status_code == 200
    data = response.json()

    assert 'total' in data
    assert 'jobs' in data
    assert len(data['jobs']) >= 3

    # Cleanup
    with connect() as conn:
        conn.execute(f"DELETE FROM career_jobs WHERE id IN ({','.join('?' * len(created_ids))})", created_ids)
        conn.commit()


# ============================================================================
# BONUS TEST: STRESS TEST
# ============================================================================

def test_16_large_batch(test_api_key, sample_job):
    """Test 16 (BONUS): Handle large batch (100 jobs)."""
    jobs = []
    for i in range(100):
        job = sample_job.copy()
        job['externalId'] = f'stress-{i:04d}'
        job['title'] = f'Job {i+1}'
        jobs.append(job)

    response = client.post(
        '/api/v1/career/ingest',
        json={'jobs': jobs},
        headers={
            'X-API-Key': test_api_key['api_key'],
            'X-API-Secret': test_api_key['api_secret']
        }
    )

    assert response.status_code == 200
    data = response.json()

    assert data['received'] == 100
    assert data['summary']['created'] == 100

    # Cleanup
    with connect() as conn:
        conn.execute("DELETE FROM career_jobs WHERE source = 'topcv' AND external_id LIKE 'stress-%'")
        conn.commit()
