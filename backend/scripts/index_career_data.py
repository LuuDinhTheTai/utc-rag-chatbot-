#!/usr/bin/env python3
"""
Index existing career jobs into RAG system.

Generates text chunks and embeddings for all career jobs in database.

Usage:
    # Activate venv first
    cd backend
    .venv/Scripts/activate  # Windows
    python scripts/index_career_data.py

    # Optional: index specific jobs
    python scripts/index_career_data.py --limit 10
    python scripts/index_career_data.py --reindex  # Re-index all jobs
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from uuid import uuid4

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.localdb import connect, now
from app.career_rag import extract_job_text, chunk_job, embed_career_jobs
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)


def get_embedding_model_id(conn):
    """Get or create embedding model record."""
    cfg = settings()

    # Check if model exists
    row = conn.execute('''
        SELECT id FROM embedding_models
        WHERE provider = 'google'
          AND model_name = ?
          AND dimensions = ?
    ''', (cfg.embedding_model, cfg.embedding_dimensions)).fetchone()

    if row:
        return row['id']

    # Create new model record
    model_id = str(uuid4())
    conn.execute('''
        INSERT INTO embedding_models (id, provider, model_name, dimensions)
        VALUES (?, 'google', ?, ?)
    ''', (model_id, cfg.embedding_model, cfg.embedding_dimensions))

    log.info(f'Created embedding model: {cfg.embedding_model} ({cfg.embedding_dimensions} dims)')
    return model_id


def get_jobs_to_index(conn, limit=None, reindex=False):
    """
    Get career jobs that need indexing.

    Args:
        conn: Database connection
        limit: Max jobs to index (None = all)
        reindex: If True, include already indexed jobs

    Returns:
        List of (job_id, title, payload) tuples
    """
    if reindex:
        # Re-index all jobs
        query = '''
            SELECT id, title, payload
            FROM career_jobs
            ORDER BY created_at DESC
        '''
        params = []
    else:
        # Only index jobs without chunks
        query = '''
            SELECT cj.id, cj.title, cj.payload
            FROM career_jobs cj
            WHERE NOT EXISTS (
                SELECT 1 FROM career_chunks cc
                WHERE cc.job_id = cj.id
            )
            ORDER BY cj.created_at DESC
        '''
        params = []

    if limit:
        query += ' LIMIT ?'
        params.append(limit)

    rows = conn.execute(query, params).fetchall()

    return [
        (row['id'], row['title'], json.loads(row['payload']))
        for row in rows
    ]


def delete_existing_chunks(conn, job_id):
    """Delete existing chunks and embeddings for a job (for re-indexing)."""
    # Delete embeddings first (foreign key constraint)
    conn.execute('''
        DELETE FROM career_chunk_embeddings
        WHERE chunk_id IN (
            SELECT id FROM career_chunks WHERE job_id = ?
        )
    ''', (job_id,))

    # Delete chunks
    result = conn.execute('''
        DELETE FROM career_chunks WHERE job_id = ?
    ''', (job_id,))

    return result.rowcount


async def index_jobs(jobs, model_id, reindex=False):
    """
    Index jobs into career_chunks and career_chunk_embeddings.

    Args:
        jobs: List of (job_id, title, payload) tuples
        model_id: Embedding model ID
        reindex: If True, delete existing chunks first

    Returns:
        Stats dict
    """
    if not jobs:
        log.info('No jobs to index')
        return {'indexed': 0, 'chunks': 0, 'embeddings': 0}

    log.info(f'Indexing {len(jobs)} jobs...')

    # Generate embeddings (this may take a while)
    try:
        results = await embed_career_jobs(jobs, batch_size=32)
    except Exception as exc:
        log.error(f'Embedding generation failed: {exc}')
        raise

    log.info(f'Generated {len(results)} embeddings')

    # Insert into database
    stats = {'indexed': 0, 'chunks': 0, 'embeddings': 0, 'reindexed': 0}
    timestamp = now()

    from pathlib import Path
    import sqlite3 as _sqlite3
    db_path = str(Path(settings().data_dir).resolve() / 'utc.sqlite3')

    conn = _sqlite3.connect(db_path, timeout=60, isolation_level=None)
    conn.row_factory = _sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')

    try:
        conn.execute('BEGIN')

        for job_id, chunk_idx, chunk_text, vector in results:
            if reindex:
                deleted = delete_existing_chunks(conn, job_id)
                if deleted > 0:
                    stats['reindexed'] += 1

            chunk_id = str(uuid4())
            conn.execute(
                'INSERT INTO career_chunks (id, job_id, chunk_index, content, created_at) VALUES (?, ?, ?, ?, ?)',
                (chunk_id, job_id, chunk_idx, chunk_text, timestamp)
            )
            stats['chunks'] += 1

            conn.execute(
                'INSERT INTO career_chunk_embeddings (chunk_id, model_id, vector, created_at) VALUES (?, ?, ?, ?)',
                (chunk_id, model_id, json.dumps(vector), timestamp)
            )
            stats['embeddings'] += 1

        stats['indexed'] = len(set(job_id for job_id, _, _, _ in results))
        conn.execute('COMMIT')
        log.info(f'Successfully indexed {stats["indexed"]} jobs')

    except Exception as exc:
        conn.execute('ROLLBACK')
        log.error(f'Database insertion failed: {exc}')
        raise
    finally:
        conn.close()

    return stats


def show_stats(conn):
    """Show indexing statistics."""
    print('\n' + '='*60)
    print('CAREER DATA INDEXING STATISTICS')
    print('='*60)

    # Total jobs
    total_jobs = conn.execute('SELECT COUNT(*) FROM career_jobs').fetchone()[0]
    print(f'Total career jobs: {total_jobs}')

    # Jobs with chunks
    indexed_jobs = conn.execute('''
        SELECT COUNT(DISTINCT job_id) FROM career_chunks
    ''').fetchone()[0]
    print(f'Jobs indexed: {indexed_jobs}')

    # Pending jobs
    pending = total_jobs - indexed_jobs
    print(f'Jobs pending: {pending}')

    if total_jobs > 0:
        coverage = (indexed_jobs / total_jobs * 100)
        print(f'Coverage: {coverage:.1f}%')

    # Total chunks
    total_chunks = conn.execute('SELECT COUNT(*) FROM career_chunks').fetchone()[0]
    print(f'\nTotal chunks: {total_chunks}')

    # Total embeddings
    total_embeddings = conn.execute('SELECT COUNT(*) FROM career_chunk_embeddings').fetchone()[0]
    print(f'Total embeddings: {total_embeddings}')

    if total_chunks > 0:
        avg_chunks = total_chunks / indexed_jobs if indexed_jobs > 0 else 0
        print(f'Avg chunks/job: {avg_chunks:.1f}')

    # Sample indexed job
    if indexed_jobs > 0:
        sample = conn.execute('''
            SELECT cj.title, cj.company_name, COUNT(cc.id) as chunk_count
            FROM career_jobs cj
            JOIN career_chunks cc ON cc.job_id = cj.id
            GROUP BY cj.id
            ORDER BY cc.created_at DESC
            LIMIT 1
        ''').fetchone()

        if sample:
            print(f'\nLatest indexed:')
            print(f'  {sample["title"]}')
            if sample['company_name']:
                print(f'  {sample["company_name"]}')
            print(f'  ({sample["chunk_count"]} chunks)')

    print('='*60)


async def main():
    parser = argparse.ArgumentParser(
        description='Index career jobs for RAG search'
    )
    parser.add_argument('--limit', type=int)
    parser.add_argument('--reindex', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print('Career Data Indexing')
    print('='*60)

    try:
        cfg = settings()
        if not cfg.google_api_key:
            print('✗ Error: GOOGLE_API_KEY not configured')
            sys.exit(1)
        print(f'✓ Using embedding model: {cfg.embedding_model}')
        print(f'  Dimensions: {cfg.embedding_dimensions}')
    except Exception as exc:
        print(f'✗ Configuration error: {exc}')
        sys.exit(1)

    # Open a single direct connection for all read operations
    from pathlib import Path
    import sqlite3 as _sqlite3
    db_path = str(Path(settings().data_dir).resolve() / 'utc.sqlite3')
    conn = _sqlite3.connect(db_path, timeout=60, isolation_level=None)
    conn.row_factory = _sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')

    try:
        model_id = get_embedding_model_id(conn)
        jobs = get_jobs_to_index(conn, args.limit, args.reindex)

        if not jobs:
            print('\n✓ All jobs are already indexed!')
            show_stats(conn)
            conn.close()
            return

        print(f'\n{"Re-indexing" if args.reindex else "Indexing"} {len(jobs)} jobs...')

        if args.dry_run:
            print('\n[DRY RUN] Would index:')
            for job_id, title, _ in jobs[:5]:
                print(f'  - {title} ({job_id})')
            if len(jobs) > 5:
                print(f'  ... and {len(jobs) - 5} more')
            conn.close()
            return

        conn.close()  # Release read connection before write

        stats = await index_jobs(jobs, model_id, args.reindex)

        print(f'\n✓ Indexing complete!')
        print(f'  Jobs indexed:        {stats["indexed"]}')
        print(f'  Chunks created:      {stats["chunks"]}')
        print(f'  Embeddings generated:{stats["embeddings"]}')
        if args.reindex and stats.get('reindexed', 0) > 0:
            print(f'  Jobs re-indexed:     {stats["reindexed"]}')

        # Reopen for stats display
        conn2 = _sqlite3.connect(db_path, timeout=30)
        conn2.row_factory = _sqlite3.Row
        show_stats(conn2)
        conn2.close()

    except KeyboardInterrupt:
        print('\n\n✗ Interrupted')
        conn.close()
        sys.exit(1)
    except Exception as exc:
        print(f'\n✗ Indexing failed: {exc}')
        import traceback
        traceback.print_exc()
        conn.close()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
