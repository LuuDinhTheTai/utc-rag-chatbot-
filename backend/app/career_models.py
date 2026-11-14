"""Career API models and content hash calculation."""
import hashlib
import json
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# CONTENT HASH (MUST MATCH Node.js crawler!)
# ============================================================================

def calculate_content_hash(job: dict[str, Any]) -> str:
    """
    Calculate content hash compatible with Node.js crawler.

    CRITICAL: Must match crawler's job-deduplicator.js EXACTLY!

    Crawler uses:
        const content = {
          type: job.type,
          title: job.title,
          url: job.url,
          company: {
            name: job.company?.name ?? null,
            url: job.company?.url ?? null,
          },
          salary: job.salary ?? null,
          location: job.location ?? null,
          experience: job.experience ?? null,
          tags: job.tags ?? [],
          remainingTags: job.remainingTags ?? [],
        };

        const hash = createHash('sha256')
          .update(JSON.stringify(content))
          .digest('hex');

    Python MUST produce identical hash!
    """

    # Build content object with EXACT field order
    content = {
        'type': job.get('type'),
        'title': job.get('title'),
        'url': job.get('url'),
        'company': {
            'name': job.get('company', {}).get('name') if isinstance(job.get('company'), dict) else None,
            'url': job.get('company', {}).get('url') if isinstance(job.get('company'), dict) else None,
        },
        'salary': job.get('salary'),
        'location': job.get('location'),
        'experience': job.get('experience'),
        'tags': job.get('tags', []),
        'remainingTags': job.get('remainingTags', []),
    }

    # JSON serialization MUST match Node.js JSON.stringify()
    # - separators=(',', ':') removes spaces (matches Node.js)
    # - sort_keys=False preserves insertion order
    # - ensure_ascii=False keeps Unicode (Node.js default)
    # - allow_nan=False rejects NaN/Infinity
    serialized = json.dumps(
        content,
        separators=(',', ':'),
        sort_keys=False,
        ensure_ascii=False,
        allow_nan=False
    )

    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


# ============================================================================
# REQUEST MODELS
# ============================================================================

class CompanyInfo(BaseModel):
    """Company information nested object."""
    model_config = ConfigDict(extra='forbid')

    name: str | None = None
    url: str | None = None
    logo: str | None = None


class SalaryInfo(BaseModel):
    """Salary information nested object."""
    model_config = ConfigDict(extra='forbid')

    raw: str | None = None
    min: float | None = None
    max: float | None = None
    currency: str | None = None
    unit: str | None = None


class LocationInfo(BaseModel):
    """Location information nested object."""
    model_config = ConfigDict(extra='forbid')

    raw: str | None = None


class ExperienceInfo(BaseModel):
    """Experience information nested object."""
    model_config = ConfigDict(extra='forbid')

    raw: str | None = None


class PublishedInfo(BaseModel):
    """Published date information nested object."""
    model_config = ConfigDict(extra='forbid')

    raw: str | None = None
    publishedAt: str | None = None


class CareerJobInput(BaseModel):
    """
    Single career job input schema.

    CRITICAL: Field names are camelCase to match crawler output!
    DO NOT change to snake_case - it will break content hash!
    """
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    # Required identity fields
    source: str = Field(min_length=1, max_length=100)
    externalId: str = Field(min_length=1, max_length=200)

    # Required content fields
    type: str = Field(default='job', max_length=50)
    title: str = Field(min_length=1, max_length=500)

    # Optional fields (can be null)
    url: str | None = Field(default=None, max_length=2000)
    company: CompanyInfo | None = None
    salary: SalaryInfo | None = None
    location: LocationInfo | None = None
    experience: ExperienceInfo | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)

    # remainingTags can be string OR null (from crawler)
    # NOT array! Crawler uses: job.remainingTags ?? []
    # But in payload it's stored as string like "+3: Docker, AWS"
    remainingTags: str | None = None

    published: PublishedInfo | None = None


class CareerIngestRequest(BaseModel):
    """Batch ingest request."""
    model_config = ConfigDict(extra='forbid')

    jobs: list[CareerJobInput] = Field(min_length=1, max_length=1000)


# ============================================================================
# RESPONSE MODELS
# ============================================================================

class CareerJobResult(BaseModel):
    """Result for a single job in batch."""

    source: str
    externalId: str
    status: Literal['created', 'updated', 'unchanged', 'rejected']
    jobId: str | None = None
    message: str | None = None


class CareerIngestSummary(BaseModel):
    """Summary statistics for batch ingest."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0


class CareerIngestResponse(BaseModel):
    """Response from batch ingest endpoint."""

    received: int
    results: list[CareerJobResult]
    summary: CareerIngestSummary


# ============================================================================
# INTERNAL MODELS (Database)
# ============================================================================

class CareerJobRecord(BaseModel):
    """Internal database record (not exposed via API)."""

    id: str
    source: str
    external_id: str
    type: str
    title: str
    company_name: str | None
    payload: str  # JSON string
    content_hash: str
    created_at: str
    updated_at: str
