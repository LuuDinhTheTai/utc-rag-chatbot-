"""Career data RAG integration - Extract, chunk, and embed job postings."""
import json
import logging
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from .rag import embeddings

log = logging.getLogger('career')


def extract_job_text(job_payload: dict[str, Any]) -> str:
    """
    Extract searchable text from job posting JSON.

    Args:
        job_payload: Parsed JSON from career_jobs.payload column

    Returns:
        Structured text optimized for semantic search

    Example output:
        '''
        Vị trí: Backend Developer
        Công ty: FPT Software
        Địa điểm: Hà Nội
        Kinh nghiệm: 2-3 năm
        Mức lương: 15-25 triệu VND/tháng
        Kỹ năng: Python, Django, PostgreSQL, Docker, AWS
        '''
    """
    parts = []

    # Title (most important)
    if title := job_payload.get('title'):
        parts.append(f"Vị trí: {title}")

    # Company info
    if company := job_payload.get('company'):
        if isinstance(company, dict) and (name := company.get('name')):
            parts.append(f"Công ty: {name}")

    # Location
    if location := job_payload.get('location'):
        if isinstance(location, dict) and (loc_raw := location.get('raw')):
            parts.append(f"Địa điểm: {loc_raw}")
        elif isinstance(location, str):
            parts.append(f"Địa điểm: {location}")

    # Experience
    if experience := job_payload.get('experience'):
        if isinstance(experience, dict) and (exp_raw := experience.get('raw')):
            parts.append(f"Kinh nghiệm: {exp_raw}")
        elif isinstance(experience, str):
            parts.append(f"Kinh nghiệm: {experience}")

    # Salary
    if salary := job_payload.get('salary'):
        if isinstance(salary, dict) and (sal_raw := salary.get('raw')):
            parts.append(f"Mức lương: {sal_raw}")
        elif isinstance(salary, str):
            parts.append(f"Mức lương: {salary}")

    # Tags (skills/technologies)
    tags = []
    if job_tags := job_payload.get('tags'):
        if isinstance(job_tags, list):
            tags.extend(str(t).strip() for t in job_tags
                       if t and not str(t).strip().endswith('...'))

    if remaining := job_payload.get('remainingTags'):
        if isinstance(remaining, str):
            import re as _re
            clean = _re.sub(r'^\+\d+:\s*', '', remaining.strip())
            for tag in clean.split(','):
                tag = tag.strip()
                if tag and not tag.endswith('...'):
                    tags.append(tag)

    if tags:
        parts.append(f"Kỹ năng: {', '.join(tags)}")

    # Job type
    if job_type := job_payload.get('type'):
        if job_type != 'job':  # Only include if non-default
            parts.append(f"Loại công việc: {job_type}")

    return '\n'.join(parts)


def chunk_job(job_text: str, job_title: str, company_name: str | None) -> list[str]:
    """
    Chunk job text for embedding.

    Most job postings are short (~200-500 chars) so usually 1 chunk.
    For longer descriptions, split intelligently.

    Args:
        job_text: Output from extract_job_text()
        job_title: Job title for prefix
        company_name: Company name for context

    Returns:
        List of text chunks (usually just 1)
    """
    # Prefix with context for better search
    prefix = f"[Việc làm: {job_title}"
    if company_name:
        prefix += f" - {company_name}"
    prefix += "]\n"

    full_text = prefix + job_text

    # Most jobs fit in 1 chunk (1200 chars)
    # But allow splitting for very detailed postings
    if len(full_text) <= 1200:
        return [full_text]

    # Use same splitter as document RAG
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=100,  # Less overlap for structured data
        separators=['\n\n', '\n', ', ', ' ']
    )

    chunks = splitter.split_text(full_text)

    # Add chunk numbers if multiple
    if len(chunks) > 1:
        return [f"{chunk} [Phần {i+1}/{len(chunks)}]" for i, chunk in enumerate(chunks)]

    return chunks


def validate_embedding_dimensions(vector: list[float], expected: int = 768) -> bool:
    """
    Validate embedding vector dimensions.

    Args:
        vector: Embedding vector from Gemini
        expected: Expected dimension count (768 for text-embedding-004)

    Returns:
        True if valid

    Raises:
        ValueError: If dimensions don't match
    """
    actual = len(vector)
    if actual != expected:
        raise ValueError(
            f"Embedding dimension mismatch: expected {expected}, got {actual}"
        )
    return True


async def embed_career_jobs(
    jobs: list[tuple[str, str, dict[str, Any]]],
    batch_size: int = 32
) -> list[tuple[str, int, str, list[float]]]:
    """
    Generate embeddings for multiple career jobs.

    Args:
        jobs: List of (job_id, title, payload_dict) tuples
        batch_size: Number of jobs to embed at once (default: 32)

    Returns:
        List of (job_id, chunk_index, chunk_text, embedding_vector) tuples

    Raises:
        ValueError: If embedding generation fails

    Example:
        jobs = [
            ('uuid1', 'Backend Dev', {'title': 'Backend Developer', ...}),
            ('uuid2', 'Frontend Dev', {'title': 'Frontend Developer', ...})
        ]

        results = await embed_career_jobs(jobs)
        # results: [
        #   ('uuid1', 0, 'Vị trí: Backend Developer...', [0.1, 0.2, ...]),
        #   ('uuid2', 0, 'Vị trí: Frontend Developer...', [0.3, 0.4, ...])
        # ]
    """
    model = embeddings()

    # Extract and chunk all jobs first
    job_chunks = []  # List of (job_id, chunk_index, chunk_text)

    for job_id, title, payload in jobs:
        try:
            text = extract_job_text(payload)
            company = None

            if company_data := payload.get('company'):
                if isinstance(company_data, dict):
                    company = company_data.get('name')

            chunks = chunk_job(text, title, company)

            for idx, chunk in enumerate(chunks):
                job_chunks.append((job_id, idx, chunk))

        except Exception as exc:
            log.error('job_text_extraction_failed job_id=%s error=%s',
                     job_id, type(exc).__name__)
            raise ValueError(f"Failed to extract text for job {job_id}: {exc}")

    if not job_chunks:
        return []

    log.info('career_embedding_start jobs=%d chunks=%d batch_size=%d',
            len(jobs), len(job_chunks), batch_size)

    # Generate embeddings in batches
    all_results = []

    for start_idx in range(0, len(job_chunks), batch_size):
        batch = job_chunks[start_idx:start_idx + batch_size]
        batch_texts = [chunk_text for _, _, chunk_text in batch]

        try:
            # Synchronous embedding (Gemini API)
            vectors = model.embed_documents(batch_texts)

            if len(vectors) != len(batch):
                raise ValueError(
                    f"Embedding batch size mismatch: requested {len(batch)}, "
                    f"got {len(vectors)}"
                )

            # Validate and collect results
            for (job_id, chunk_idx, chunk_text), vector in zip(batch, vectors):
                validate_embedding_dimensions(vector)
                all_results.append((job_id, chunk_idx, chunk_text, vector))

        except Exception as exc:
            log.error('career_embedding_batch_failed start=%d size=%d error=%s',
                     start_idx, len(batch), type(exc).__name__)
            raise ValueError(f"Embedding generation failed at batch {start_idx}: {exc}")

    log.info('career_embedding_complete jobs=%d chunks=%d',
            len(jobs), len(all_results))

    return all_results


def job_text_for_generation(job_payload: dict[str, Any], source_url: str | None = None) -> str:
    """
    Format job data for LLM generation (more detail than search text).

    Args:
        job_payload: Job JSON payload
        source_url: Original job URL

    Returns:
        Formatted text for answer generation
    """
    lines = []

    if title := job_payload.get('title'):
        lines.append(f"**{title}**")

    if company := job_payload.get('company'):
        if isinstance(company, dict) and (name := company.get('name')):
            lines.append(f"Công ty: {name}")
            if url := company.get('url'):
                lines.append(f"Website: {url}")

    if location := job_payload.get('location'):
        if isinstance(location, dict) and (loc_raw := location.get('raw')):
            lines.append(f"Địa điểm: {loc_raw}")

    if experience := job_payload.get('experience'):
        if isinstance(experience, dict) and (exp_raw := experience.get('raw')):
            lines.append(f"Yêu cầu kinh nghiệm: {exp_raw}")

    if salary := job_payload.get('salary'):
        if isinstance(salary, dict) and (sal_raw := salary.get('raw')):
            lines.append(f"Mức lương: {sal_raw}")

    # Combine all tags
    all_tags = []
    if tags := job_payload.get('tags'):
        if isinstance(tags, list):
            all_tags.extend(str(t).strip() for t in tags
                           if t and not str(t).strip().endswith('...'))

    if remaining := job_payload.get('remainingTags'):
        if isinstance(remaining, str):
            import re as _re
            # Strip "+N:" prefix: "+3: Tag A, Tag B" → "Tag A, Tag B"
            clean = _re.sub(r'^\+\d+:\s*', '', remaining.strip())
            for tag in clean.split(','):
                tag = tag.strip()
                # Skip items truncated by TopCV (ending with ...)
                if tag and not tag.endswith('...'):
                    all_tags.append(tag)

    if all_tags:
        lines.append(f"Kỹ năng yêu cầu: {', '.join(all_tags)}")

    if source_url:
        lines.append(f"Link: {source_url}")

    return '\n'.join(lines)
