"""Offline v1 -> v2 conversion. Never mutate a legacy database during web requests."""
from contextlib import closing
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from .v2store import ensure_model, import_cutoff_rows, insert_row, timestamp, write

VERSION = 'schema_v2'
DDL = Path(__file__).resolve().parents[1] / 'schema/v2.sql'


def is_v2(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone():
        return False
    return bool(conn.execute('SELECT 1 FROM schema_migrations WHERE version=?',(VERSION,)).fetchone())


def initialize(conn):
    conn.execute('BEGIN IMMEDIATE')
    try:
        if is_v2(conn):
            conn.rollback()
            return
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
            raise RuntimeError('Legacy database: stop services and run scripts/migrate_database.py --apply --offline')
        statement = ''
        for line in DDL.read_text().splitlines(True):
            statement += line
            if sqlite3.complete_statement(statement):
                # Execute separately to keep DDL + marker atomic (executescript commits).
                sql = statement.strip()
                statement = ''
                meaningful = '\n'.join(l for l in sql.splitlines() if not l.lstrip().startswith('--')).strip()
                if meaningful in ('PRAGMA foreign_keys = ON;','BEGIN IMMEDIATE;','COMMIT;'):
                    continue
                if meaningful:
                    conn.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def check(conn):
    if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('Database integrity check failed')
    if conn.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Database contains broken foreign keys')


def rows(conn, table):
    return [dict(r) for r in conn.execute(f'SELECT * FROM {table}')]


def columns(conn, table):
    return {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}


def digest(conn):
    # Hash logical content, including WAL-visible data; never expose row values.
    result = hashlib.sha256()
    for line in conn.iterdump():
        result.update(line.encode())
        result.update(b'\n')
    return result.hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def manifest(root):
    return {str(p.relative_to(root)):file_digest(p) for p in sorted(root.rglob('*')) if p.is_file()} if root.exists() else {}


def open_db(path):
    conn = sqlite3.connect(path,timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def convert(source, target, embedding_model=None, dimensions=768):
    """source is a disposable copy upgraded by legacydb.prepare, not the original."""
    if not 1 <= dimensions <= 3072:
        raise ValueError('Embedding dimensions must be between 1 and 3072')
    from .legacydb import prepare
    prepare(source)
    check(source)
    initialize(target)
    stamp = timestamp()
    report = {'counts':{},'orphan_document_authors':[], 'unlinked_citations':0}
    target.execute('BEGIN IMMEDIATE')
    try:
        accounts = rows(source,'accounts')
        # Older user-owned chat must stay private after conversion.
        if columns(source,'users'):
            for user in rows(source,'users'):
                if not any(a['id']==user['id'] for a in accounts):
                    accounts.append(dict(id=user['id'],email=user['email'],display_name='',password_hash=user['password_hash'],role='student',is_active=1,created_at=user['created_at'],updated_at=user['created_at']))
        for record in accounts:
            insert_row(target,'accounts',record)
        ids = {a['id'] for a in accounts}
        for table in ('auth_sessions','api_rate_limits','freshman_guides','freshman_items'):
            for record in rows(source,table):
                insert_row(target,table,record)
        for record in rows(source,'chat_sessions'):
            old_user = record.pop('user_id',None)
            if not record.get('account_id') and old_user:
                record['account_id'] = old_user
            insert_row(target,'chat_sessions',record)
        for record in rows(source,'major_catalogue'):
            for field in ('methods','subject_groups'):
                record[field] = json.loads(record[field])
            write(target,'major_catalogue',record)
        cutoffs = rows(source,'cutoff_scores')
        import_cutoff_rows(target,[tuple(r[k] for k in ('admission_year','campus','admission_code','program_name','method','score','scale','source_url','note','search_text')) for r in cutoffs])
        for record in rows(source,'documents'):
            record['updated_at'] = record['created_at']
            if record.get('created_by') and record['created_by'] not in ids:
                report['orphan_document_authors'].append({'document_id':record['id'],'legacy_author_id':record['created_by']})
                record['created_by'] = None
            write(target,'documents',record)
        chunks = rows(source,'document_chunks')
        if chunks and not embedding_model:
            raise ValueError('Existing vectors require an explicitly verified --embedding-model; do not infer it from current settings')
        if chunks:
            key = ensure_model(target,embedding_model,dimensions)
            for record in chunks:
                vector = record.pop('embedding')
                insert_row(target,'document_chunks',record)
                target.execute('INSERT INTO chunk_embeddings VALUES (?,?,?,?)',(record['id'],key,vector,stamp))
        for record in rows(source,'messages'):
            record['sources'] = json.loads(record['sources'])
            write(target,'messages',record)
        for record in rows(source,'feedback'):
            insert_row(target,'feedback',record)
        for record in rows(source,'schema_migrations'):
            if record['version'] != VERSION:
                insert_row(target,'schema_migrations',record)
        for table in ('accounts','auth_sessions','chat_sessions','messages','feedback','documents','document_chunks','major_catalogue','cutoff_scores','freshman_guides','freshman_items','api_rate_limits'):
            expected = len(accounts) if table=='accounts' else source.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            actual = target.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            if expected != actual:
                raise ValueError(f'Row count mismatch in {table}')
            report['counts'][table] = actual
        # Compare every legacy field represented by the API, not just row counts.
        from .v2store import relation
        json_fields = {'sources','methods','subject_groups','embedding'}
        for table in ('accounts','auth_sessions','chat_sessions','messages','feedback','documents','document_chunks','major_catalogue','freshman_guides','freshman_items'):
            for record in rows(source,table):
                lookup = 'token_hash' if table == 'auth_sessions' else 'id'
                found = target.execute(f'SELECT * FROM {relation(table)} WHERE {lookup}=?',(record[lookup],)).fetchone()
                for field,value in record.items():
                    if field in {'user_id','chunk_count'}:
                        continue  # user_id is mapped to account_id; chunk_count is derived.
                    actual = found[field]
                    if table == 'chat_sessions' and field == 'account_id' and not value:
                        value = record.get('user_id')
                    if table == 'documents' and field == 'created_by' and value not in ids:
                        value = None
                    if field == 'embedding':
                        actual = target.execute('SELECT vector FROM chunk_embeddings WHERE chunk_id=? AND model_id=?',(record['id'],key)).fetchone()[0]
                    if field in json_fields:
                        value,actual = json.loads(value),json.loads(actual)
                    if value != actual:
                        raise ValueError(f'Value round-trip mismatch in {table}.{field}')
        for record in cutoffs:
            found = target.execute(f"SELECT * FROM {relation('cutoff_scores')} WHERE admission_year=? AND campus=? AND admission_code=? AND method=?",tuple(record[k] for k in ('admission_year','campus','admission_code','method'))).fetchone()
            if any(record[k] != found[k] for k in record):
                raise ValueError('Value round-trip mismatch in cutoff_scores')
        report['unlinked_citations'] = target.execute('SELECT count(*) FROM message_citations WHERE chunk_id IS NULL').fetchone()[0]
        check(target)
        target.commit()
        return report
    except Exception:
        target.rollback()
        raise


def migrate(data_dir, *, apply=False, offline=False, embedding_model=None, dimensions=768):
    data_dir = Path(data_dir).resolve()
    database = data_dir / 'utc.sqlite3'
    if not database.is_file():
        raise ValueError('No existing utc.sqlite3 to migrate')
    if apply and not offline:
        raise ValueError('Stop all services and pass --offline before applying migration')
    with closing(open_db(database)) as original:
        if is_v2(original):
            check(original)
            return {'status':'already_v2'}
        # Avoid overwriting application/plugin tables that the converter does not know.
        known = {'admins','admin_sessions','schema_migrations','accounts','auth_sessions','api_rate_limits','chat_sessions','messages','feedback','documents','document_chunks','major_catalogue','cutoff_scores','freshman_guides','freshman_items','users'}
        actual = {r[0] for r in original.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if actual-known:
            raise ValueError('Unrecognized tables; migration requires an explicit mapping')
        before = digest(original)
        with tempfile.TemporaryDirectory(prefix='utc-migrate-',dir=data_dir.parent) as scratch:
            scratch = Path(scratch)
            with closing(open_db(scratch/'legacy.sqlite3')) as legacy:
                original.backup(legacy)
                with closing(open_db(scratch/'v2.sqlite3')) as target:
                    report = convert(legacy,target,embedding_model,dimensions)
                    expected = digest(target)
            if not apply:
                return {'status':'validated','report':report}
            # An offline caller must have stopped background indexers and all servers.
            # Switching journal mode fails if another connection still holds WAL locks.
            original.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            if original.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
                raise ValueError('Could not leave WAL mode; stop all database connections')
            original.execute('BEGIN EXCLUSIVE')
            if digest(original) != before:
                raise ValueError('Database changed during conversion; retry while offline')
            backup = Path(tempfile.mkdtemp(prefix='utc-v1-backup-',dir=data_dir.parent))
            backup.chmod(0o700)
            # Separate reader can see the same committed data under this RESERVED lock.
            # EXCLUSIVE locks disallow that, so preserve the checkpointed database file.
            shutil.copy2(database,backup/'utc.sqlite3')
            files = manifest(data_dir/'files')
            if (data_dir/'files').exists():
                shutil.copytree(data_dir/'files',backup/'files')
            if manifest(backup/'files') != files or manifest(data_dir/'files') != files:
                raise ValueError('File backup verification failed')
            with closing(open_db(backup/'utc.sqlite3')) as saved:
                check(saved)
                if digest(saved) != before:
                    raise ValueError('Database backup verification failed')
            metadata = {'v1_digest':before,'v2_digest':expected,'files':files,'report':report}
            (backup/'migration.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
            original.rollback()
            original.close()
            (scratch/'v2.sqlite3').chmod(database.stat().st_mode & 0o777)
            (scratch/'v2.sqlite3').replace(database)
            return {'status':'migrated','backup':str(backup),'report':report}


def rollback(data_dir, backup, *, offline=False):
    if not offline:
        raise ValueError('Stop services and pass --offline before rollback')
    data_dir,backup = Path(data_dir).resolve(),Path(backup).resolve()
    metadata = json.loads((backup/'migration.json').read_text())
    with closing(open_db(data_dir/'utc.sqlite3')) as current:
        if digest(current) != metadata['v2_digest'] or manifest(data_dir/'files') != metadata['files']:
            raise ValueError('Database/files changed after migration; rollback would lose new data')
        current.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        current.execute('PRAGMA journal_mode=DELETE')
        with closing(open_db(backup/'utc.sqlite3')) as old:
            check(old)
            if digest(old) != metadata['v1_digest'] or manifest(backup/'files') != metadata['files']:
                raise ValueError('Backup content changed; refusing rollback')
        current.close()
        temporary = data_dir/'utc.rollback.sqlite3'
        if temporary.exists():
            raise ValueError('Rollback staging file already exists')
        shutil.copy2(backup/'utc.sqlite3',temporary)
        temporary.replace(data_dir/'utc.sqlite3')
    return {'status':'rolled_back'}
