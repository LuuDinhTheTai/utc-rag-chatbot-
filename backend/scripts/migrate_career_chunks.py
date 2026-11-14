#!/usr/bin/env python3
"""
Apply career_chunks.sql migration to existing database.

Creates tables for career data RAG integration:
- career_chunks: Job text chunks for semantic search
- career_chunk_embeddings: Vector embeddings for chunks

Usage:
    python scripts/migrate_career_chunks.py
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.localdb import connect, now


def check_tables_exist(conn):
    """Check if career chunk tables already exist."""
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]

    has_chunks = 'career_chunks' in tables
    has_embeddings = 'career_chunk_embeddings' in tables

    return has_chunks, has_embeddings


def apply_migration(conn):
    """Apply career chunks schema migration."""

    print('Checking existing schema...')
    has_chunks, has_embeddings = check_tables_exist(conn)

    if has_chunks and has_embeddings:
        print('✓ Migration already applied. Tables exist.')
        return False

    if has_chunks or has_embeddings:
        print('⚠️  Partial migration detected!')
        print(f'   career_chunks: {"EXISTS" if has_chunks else "MISSING"}')
        print(f'   career_chunk_embeddings: {"EXISTS" if has_embeddings else "MISSING"}')

        response = input('Drop and recreate tables? (y/N): ')
        if response.lower() != 'y':
            print('Aborted.')
            return False

        print('Dropping partial tables...')
        if has_embeddings:
            conn.execute('DROP TABLE IF EXISTS career_chunk_embeddings')
        if has_chunks:
            conn.execute('DROP TABLE IF EXISTS career_chunks')

    print('Applying migration...')

    # Read and execute schema
    schema_path = Path(__file__).parent.parent / 'schema' / 'career_chunks.sql'

    if not schema_path.exists():
        print(f'✗ Schema file not found: {schema_path}')
        return False

    with open(schema_path) as f:
        sql = f.read()

    # Execute entire schema (it's wrapped in a transaction)
    try:
        conn.executescript(sql)
        print('✓ Schema applied successfully')
    except Exception as exc:
        print(f'✗ Migration failed: {exc}')
        raise

    # Verify tables were created
    has_chunks, has_embeddings = check_tables_exist(conn)

    if not (has_chunks and has_embeddings):
        print('✗ Migration verification failed')
        return False

    print('✓ Migration verified')

    # Check if embedding_models table has Google model
    models = conn.execute(
        "SELECT * FROM embedding_models WHERE provider='google'"
    ).fetchall()

    if not models:
        print('\n⚠️  No Google embedding model found in embedding_models table.')
        print('   You may need to run a job embedding to register the model.')
    else:
        print(f'\n✓ Found {len(models)} Google embedding model(s)')
        for model in models:
            print(f'   - {model["model_name"]} ({model["dimensions"]} dims)')

    return True


def show_stats(conn):
    """Show career data statistics."""
    print('\n' + '='*60)
    print('CAREER DATA STATISTICS')
    print('='*60)

    # Career jobs count
    jobs_count = conn.execute('SELECT COUNT(*) FROM career_jobs').fetchone()[0]
    print(f'Career jobs: {jobs_count}')

    # Career chunks count
    chunks_count = conn.execute('SELECT COUNT(*) FROM career_chunks').fetchone()[0]
    print(f'Career chunks: {chunks_count}')

    # Career embeddings count
    embeddings_count = conn.execute('SELECT COUNT(*) FROM career_chunk_embeddings').fetchone()[0]
    print(f'Career embeddings: {embeddings_count}')

    if jobs_count > 0 and chunks_count == 0:
        print('\n⚠️  You have career jobs but no chunks yet.')
        print('   Run: python scripts/index_career_data.py')
    elif chunks_count > 0 and embeddings_count == 0:
        print('\n⚠️  You have chunks but no embeddings yet.')
        print('   Run: python scripts/index_career_data.py')
    elif embeddings_count > 0:
        print(f'\n✓ Ready for career queries!')
        coverage = (embeddings_count / chunks_count * 100) if chunks_count > 0 else 0
        print(f'   Embedding coverage: {coverage:.1f}%')


def main():
    print('Career Chunks Migration')
    print('='*60)

    try:
        with connect() as conn:
            # Apply migration
            applied = apply_migration(conn)

            if applied:
                print('\n✓ Migration completed successfully!')

            # Show stats
            show_stats(conn)

    except Exception as exc:
        print(f'\n✗ Migration failed: {exc}')
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print('\n' + '='*60)
    print('Next steps:')
    print('  1. Run: python scripts/index_career_data.py')
    print('  2. Test career queries in chatbot')
    print('='*60)


if __name__ == '__main__':
    main()
