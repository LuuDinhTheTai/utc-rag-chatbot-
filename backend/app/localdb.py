"""Small SQLite store for the self-hosted deployment.

The query facade keeps the existing route handlers independent of a hosted data API.
Each operation uses its own connection so FastAPI background tasks can write safely.
"""
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import settings


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS admins (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'admin' CHECK(role IN ('admin','editor','viewer')), is_active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS admin_sessions (token_hash TEXT PRIMARY KEY, admin_id TEXT NOT NULL REFERENCES admins(id) ON DELETE CASCADE, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, email TEXT NOT NULL COLLATE NOCASE UNIQUE, display_name TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('student','lecturer','admin')), is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_sessions (token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS auth_sessions_account ON auth_sessions(account_id);
CREATE TABLE IF NOT EXISTS api_rate_limits (key TEXT NOT NULL, window_start INTEGER NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(key,window_start));
CREATE INDEX IF NOT EXISTS api_rate_limits_window ON api_rate_limits(window_start);
CREATE TABLE IF NOT EXISTS chat_sessions (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, question TEXT, sources TEXT NOT NULL DEFAULT '[]', supported INTEGER, latency_ms INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, message_id TEXT UNIQUE NOT NULL REFERENCES messages(id) ON DELETE CASCADE, rating INTEGER NOT NULL, comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, title TEXT NOT NULL, source_url TEXT NOT NULL, admission_year INTEGER NOT NULL, campus TEXT NOT NULL, category TEXT NOT NULL, checksum TEXT UNIQUE NOT NULL, raw_text TEXT NOT NULL, status TEXT NOT NULL, chunk_count INTEGER NOT NULL DEFAULT 0, error TEXT, created_by TEXT, storage_path TEXT, original_filename TEXT, original_size INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS document_chunks (id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, chunk_index INTEGER NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL, UNIQUE(document_id, chunk_index));
CREATE INDEX IF NOT EXISTS chunks_document ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS documents_filter ON documents(admission_year,campus,status);
CREATE TABLE IF NOT EXISTS major_catalogue (id TEXT PRIMARY KEY, admission_code TEXT NOT NULL, major_code TEXT NOT NULL, name TEXT NOT NULL, program_name TEXT NOT NULL, admission_year INTEGER NOT NULL, campus TEXT NOT NULL, quota INTEGER, methods TEXT NOT NULL DEFAULT '[]', subject_groups TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, search_text TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(admission_year,campus,admission_code));
CREATE TABLE IF NOT EXISTS cutoff_scores (admission_year INTEGER NOT NULL, campus TEXT NOT NULL CHECK(campus IN ('hanoi','hcm')), admission_code TEXT NOT NULL, program_name TEXT NOT NULL, method TEXT NOT NULL CHECK(method IN ('PT1','PT2','PT3','PT4')), score REAL NOT NULL, scale INTEGER NOT NULL, source_url TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', search_text TEXT NOT NULL, PRIMARY KEY(admission_year,campus,admission_code,method));
CREATE INDEX IF NOT EXISTS cutoff_scores_filters ON cutoff_scores(admission_year,campus,method);
CREATE TABLE IF NOT EXISTS freshman_guides (id TEXT PRIMARY KEY, cohort TEXT UNIQUE NOT NULL, admission_year INTEGER NOT NULL, title TEXT NOT NULL, storage_path TEXT NOT NULL, is_published INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS freshman_items (id TEXT PRIMARY KEY, guide_id TEXT NOT NULL REFERENCES freshman_guides(id) ON DELETE CASCADE, code TEXT NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL, applies_to TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '', source_page INTEGER NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(guide_id,category,code));
"""
JSON_FIELDS = {'sources', 'embedding', 'methods', 'subject_groups'}
BOOL_FIELDS = {'supported', 'is_active', 'is_published'}
TABLES = {'chat_sessions', 'messages', 'feedback', 'documents', 'document_chunks', 'major_catalogue', 'freshman_guides', 'freshman_items'}


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    path = Path(settings().data_dir).resolve() / 'utc.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript(SCHEMA)
    message_columns = {row['name'] for row in conn.execute('PRAGMA table_info(messages)')}
    for name, kind in [('resolved_question', 'TEXT'), ('context_year', 'INTEGER'), ('context_campus', 'TEXT')]:
        if name not in message_columns:
            conn.execute(f'ALTER TABLE messages ADD COLUMN {name} {kind}')
    conn.execute('CREATE INDEX IF NOT EXISTS messages_session_created ON messages(session_id,created_at)')
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(admins)')}
    if 'role' not in columns:
        conn.execute("ALTER TABLE admins ADD COLUMN role TEXT NOT NULL DEFAULT 'admin' CHECK(role IN ('admin','editor','viewer'))")
    if 'is_active' not in columns:
        conn.execute('ALTER TABLE admins ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1')
    conn.commit()
    # Run once under a write lock. Preserve legacy rows and IDs for audit/foreign keys;
    # legacy session tokens are intentionally not accepted by the new auth module.
    conn.execute('BEGIN IMMEDIATE')
    try:
        if not conn.execute("SELECT 1 FROM schema_migrations WHERE version='accounts_v1'").fetchone():
            timestamp = now()
            conn.execute("INSERT INTO accounts(id,email,display_name,password_hash,role,is_active,created_at,updated_at) "
                         "SELECT id,lower(trim(email)),'',password_hash,CASE role WHEN 'editor' THEN 'lecturer' WHEN 'viewer' THEN 'student' ELSE 'admin' END,is_active,?,? FROM admins",
                         (timestamp, timestamp))
            conn.execute("INSERT INTO schema_migrations VALUES('accounts_v1',?)", (timestamp,))
        session_columns = {row['name'] for row in conn.execute('PRAGMA table_info(chat_sessions)')}
        if 'account_id' not in session_columns:
            conn.execute('ALTER TABLE chat_sessions ADD COLUMN account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE')
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    return conn


def decoded(row):
    value = dict(row)
    for key in JSON_FIELDS & value.keys():
        value[key] = json.loads(value[key]) if isinstance(value[key], str) else value[key]
    for key in BOOL_FIELDS & value.keys():
        value[key] = bool(value[key]) if value[key] is not None else None
    return value


def encoded(value):
    return {k: json.dumps(v, ensure_ascii=False) if k in JSON_FIELDS else int(v) if k in BOOL_FIELDS and v is not None else v for k, v in value.items()}


@dataclass
class Result:
    data: object
    count: int | None = None


class Query:
    def __init__(self, table):
        if table not in TABLES:
            raise ValueError('Unknown table')
        self.table = table
        self.mode = 'select'
        self.fields = '*'
        self.values = None
        self.where = []
        self.params = []
        self.sort = []
        self.max_rows = None
        self.offset = 0
        self.want_count = False
        self.conflict = None
        self.ignore_duplicates = False

    def select(self, fields='*', count=None):
        self.mode, self.fields, self.want_count = 'select', fields, count == 'exact'
        return self

    def eq(self, field, value):
        self.where.append(f'{field} = ?')
        self.params.append(int(value) if isinstance(value, bool) else value)
        return self

    def in_(self, field, values):
        self.where.append(f'{field} IN ({",".join("?" for _ in values)})')
        self.params.extend(values)
        return self

    def ilike(self, field, pattern):
        self.where.append(f"{field} LIKE ? ESCAPE '\\'")
        self.params.append(pattern)
        return self

    def order(self, field, desc=False):
        self.sort.append(f'{field} {"DESC" if desc else "ASC"}')
        return self

    def limit(self, count):
        self.max_rows = count
        return self

    def range(self, start, end):
        self.offset, self.max_rows = start, end - start + 1
        return self

    def insert(self, values):
        self.mode, self.values = 'insert', values
        return self

    def update(self, values):
        self.mode, self.values = 'update', values
        return self

    def delete(self):
        self.mode = 'delete'
        return self

    def upsert(self, values, on_conflict=None, ignore_duplicates=False):
        self.mode, self.values = 'upsert', values
        self.conflict, self.ignore_duplicates = on_conflict, ignore_duplicates
        return self

    def execute(self):
        clause = ' WHERE ' + ' AND '.join(self.where) if self.where else ''
        with connect() as conn:
            if self.mode == 'select':
                fields = self.fields
                if fields != '*' and '(' not in fields:
                    fields = ','.join(f.strip() for f in fields.split(','))
                elif '(' in fields:
                    fields = '*'
                total = conn.execute(f'SELECT count(*) FROM {self.table}{clause}', self.params).fetchone()[0] if self.want_count else None
                sql = f'SELECT {fields} FROM {self.table}{clause}'
                if self.sort:
                    sql += ' ORDER BY ' + ','.join(self.sort)
                if self.max_rows is not None:
                    sql += ' LIMIT ? OFFSET ?'
                    rows = conn.execute(sql, self.params + [self.max_rows, self.offset]).fetchall()
                else:
                    rows = conn.execute(sql, self.params).fetchall()
                return Result([decoded(row) for row in rows], total)
            if self.mode in {'insert', 'upsert'}:
                records = self.values if isinstance(self.values, list) else [self.values]
                result = []
                for record in records:
                    record = encoded({'id': str(uuid4())} | ({'created_at': now()} if self.table != 'document_chunks' else {}) | record)
                    if self.table in {'major_catalogue', 'freshman_guides', 'freshman_items'}:
                        record.setdefault('updated_at', now())
                    columns = list(record)
                    verb = 'INSERT OR IGNORE' if self.mode == 'upsert' and self.ignore_duplicates else 'INSERT'
                    sql = f'{verb} INTO {self.table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})'
                    if self.mode == 'upsert' and not self.ignore_duplicates:
                        target = self.conflict or 'id'
                        updates = ','.join(f'{k}=excluded.{k}' for k in columns if k not in target.split(',') and k not in {'id','created_at'})
                        sql += f' ON CONFLICT({target}) DO UPDATE SET {updates}'
                    cursor = conn.execute(sql, list(record.values()))
                    if cursor.rowcount:
                        if self.mode == 'upsert' and self.conflict and not self.ignore_duplicates:
                            fields = self.conflict.split(',')
                            lookup = ' AND '.join(f'{field}=?' for field in fields)
                            found = conn.execute(f'SELECT * FROM {self.table} WHERE {lookup}',
                                                 [record[field] for field in fields]).fetchone()
                        else:
                            found = conn.execute(f'SELECT * FROM {self.table} WHERE id=?', (record['id'],)).fetchone()
                        result.append(decoded(found))

                return Result(result)
            rows = conn.execute(f'SELECT * FROM {self.table}{clause}', self.params).fetchall()
            if self.mode == 'update':
                value = encoded(self.values)
                sql = f'UPDATE {self.table} SET ' + ','.join(f'{k}=?' for k in value) + clause
                conn.execute(sql, list(value.values()) + self.params)
                return Result([decoded(conn.execute(f'SELECT * FROM {self.table} WHERE id=?', (row['id'],)).fetchone()) for row in rows])
            conn.execute(f'DELETE FROM {self.table}{clause}', self.params)
            return Result([decoded(row) for row in rows])


class StorageBucket:
    def _path(self, path):
        root = (Path(settings().data_dir).resolve() / 'files').resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise ValueError('Invalid storage path')
        return target

    def upload(self, path, data, options=None):
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as handle:
            handle.write(data)

    def download(self, path):
        return self._path(path).read_bytes()

    def remove(self, paths):
        for path in paths:
            self._path(path).unlink(missing_ok=True)


class Storage:
    def from_(self, bucket):
        if bucket != 'admission-documents':
            raise ValueError('Unknown bucket')
        return StorageBucket()


class Database:
    def __init__(self):
        self.storage = Storage()

    def table(self, name):
        return Query(name)

    def rpc(self, name, args):
        return RPC(name, args)


class RPC:
    def __init__(self, name, args):
        self.name, self.args = name, args

    def execute(self):
        if self.name == 'match_chunks':
            a = self.args
            with connect() as conn:
                rows = conn.execute('SELECT c.id,c.document_id,c.content,c.embedding,d.title,d.source_url,d.admission_year,d.campus FROM document_chunks c JOIN documents d ON d.id=c.document_id WHERE d.status=? AND d.admission_year=? AND d.campus=?', ('ready', a['filter_year'], a['filter_campus'])).fetchall()
            query = a['query_embedding']
            norm = math.sqrt(sum(x*x for x in query))
            result = []
            for row in rows:
                item = decoded(row)
                vector = item.pop('embedding')
                denominator = norm * math.sqrt(sum(x*x for x in vector))
                score = sum(x*y for x,y in zip(query,vector)) / denominator if denominator else 0
                if score >= a['min_similarity']:
                    result.append(item | {'similarity': score})
            result.sort(key=lambda item: item['similarity'], reverse=True)
            return Result(result[:a['match_count']])
        if self.name == 'save_major':
            return Result(save_major(self.args['p_data'], self.args.get('p_id')))
        if self.name == 'delete_major':
            return Result(bool(Query('major_catalogue').delete().eq('id', self.args['p_id']).execute().data))
        if self.name == 'import_majors':
            inserted = skipped = 0
            with connect() as conn:
                for row in self.args['p_rows']:
                    existing = conn.execute(
                        'SELECT id FROM major_catalogue WHERE admission_year=? AND campus=? AND admission_code=?',
                        (row['admission_year'], row['campus'], row['admission_code'])).fetchone()
                    if existing:
                        skipped += 1
                        continue
                    record = encoded({
                        'id': str(uuid4()), 'created_at': now(), 'updated_at': now(),
                        'search_text': ' '.join(str(row[k]) for k in
                                                ('admission_code','major_code','name','program_name'))
                    } | row)
                    columns = list(record)
                    conn.execute(
                        f'INSERT INTO major_catalogue ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
                        list(record.values()))
                    inserted += 1
            return Result({'inserted': inserted, 'skipped': skipped, 'total': inserted + skipped})
        raise ValueError('Unknown RPC')


def save_major(data, major_id=None):
    record = data | {'search_text': ' '.join(str(data[k]) for k in ('admission_code','major_code','name','program_name'))}
    if major_id:
        return (Query('major_catalogue').update(record | {'updated_at': now()}).eq('id',major_id).execute().data or [None])[0]
    return Query('major_catalogue').insert(record).execute().data[0]
