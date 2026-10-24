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
from .v2store import relation, write


JSON_FIELDS = {'sources', 'embedding', 'methods', 'subject_groups'}
BOOL_FIELDS = {'supported', 'is_active', 'is_published'}
TABLES = {'chat_sessions', 'messages', 'feedback', 'documents', 'document_chunks', 'major_catalogue', 'freshman_guides', 'freshman_items'}


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    from .migrations import initialize, is_v2
    path = Path(settings().data_dir).resolve() / 'utc.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        if not is_v2(conn):
            initialize(conn)  # Empty databases only; legacy migration must be explicit/offline.
        from .planner_schema import ensure_planner
        ensure_planner(conn)
        from .conversation_schema import ensure_conversations
        ensure_conversations(conn)
        from .routing_schema import ensure_routing
        ensure_routing(conn)
        conn.execute('PRAGMA journal_mode=WAL')
        return conn
    except Exception:
        conn.close()
        raise


def decoded(row):
    value = dict(row)
    if "campus" in value:
        value.pop("campus_code", None)
    for key in JSON_FIELDS & value.keys():
        value[key] = json.loads(value[key]) if isinstance(value[key], str) else value[key]
    for key in BOOL_FIELDS & value.keys():
        value[key] = bool(value[key]) if value[key] is not None else None
    return value



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
        source = relation(self.table)
        with connect() as conn:
            if self.mode == 'select':
                fields = self.fields
                if fields != '*' and '(' not in fields:
                    fields = ','.join(f.strip() for f in fields.split(','))
                elif '(' in fields:
                    fields = '*'
                total = conn.execute(f'SELECT count(*) FROM {source}{clause}', self.params).fetchone()[0] if self.want_count else None
                sql = f'SELECT {fields} FROM {source}{clause}'
                if self.sort:
                    sql += ' ORDER BY ' + ','.join(self.sort)
                if self.max_rows is not None:
                    sql += ' LIMIT ? OFFSET ?'
                    rows = conn.execute(sql, self.params + [self.max_rows, self.offset]).fetchall()
                else:
                    rows = conn.execute(sql, self.params).fetchall()
                return Result([decoded(row) for row in rows], total)
            # Serialize composite writes and upsert conflict checks in one transaction.
            conn.execute('BEGIN IMMEDIATE')
            if self.mode in {'insert', 'upsert'}:
                records = self.values if isinstance(self.values, list) else [self.values]
                result = []
                for values in records:
                    record = {'id': str(uuid4())} | ({'created_at': now()} if self.table != 'document_chunks' else {}) | values
                    if self.table in {'major_catalogue','freshman_guides','freshman_items','documents'}:
                        record.setdefault('updated_at', now())
                    found = None
                    if self.mode == 'upsert':
                        fields = (self.conflict or 'id').split(',')
                        lookup = ' AND '.join(f'{field}=?' for field in fields)
                        found = conn.execute(f'SELECT * FROM {source} WHERE {lookup}', [record[field] for field in fields]).fetchone()
                    if found and self.ignore_duplicates:
                        continue
                    if found:
                        record = decoded(found) | values | {'id':found['id']}
                    identifier = write(conn,self.table,record,update=bool(found))
                    result.append(decoded(conn.execute(f'SELECT * FROM {source} WHERE id=?',(identifier,)).fetchone()))
                return Result(result)
            rows = conn.execute(f'SELECT * FROM {source}{clause}', self.params).fetchall()
            if self.mode == 'update':
                result = []
                for row in rows:
                    record = decoded(row) | self.values
                    if self.table in {'major_catalogue','documents','freshman_guides','freshman_items'}:
                        record['updated_at'] = now()
                    identifier = write(conn,self.table,record,update=True)
                    result.append(decoded(conn.execute(f'SELECT * FROM {source} WHERE id=?',(identifier,)).fetchone()))
                return Result(result)
            for row in rows:
                conn.execute(f'DELETE FROM {self.table} WHERE id=?',(row['id'],))
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
                from .v2store import model_id
                rows = conn.execute('SELECT c.id,c.document_id,c.content,e.vector AS embedding,d.title,d.source_url,d.admission_year,d.campus_code AS campus FROM document_chunks c JOIN chunk_embeddings e ON e.chunk_id=c.id JOIN documents d ON d.id=c.document_id WHERE d.status=? AND d.admission_year=? AND d.campus_code=? AND e.model_id=?', ('ready', a['filter_year'], a['filter_campus'], model_id())).fetchall()
            query = a['query_embedding']
            if len(query) != settings().embedding_dimensions:
                raise ValueError('Query embedding dimensions do not match configured model')
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
                conn.execute('BEGIN IMMEDIATE')
                for row in self.args['p_rows']:
                    existing = conn.execute(
                        'SELECT m.id FROM major_catalogue m JOIN admission_offerings o ON o.id=m.id WHERE o.admission_year=? AND o.campus_code=? AND o.admission_code=?',
                        (row['admission_year'], row['campus'], row['admission_code'])).fetchone()
                    if existing:
                        skipped += 1
                        continue
                    record = {
                        'id': str(uuid4()), 'created_at': now(), 'updated_at': now(),
                        'search_text': ' '.join(str(row[k]) for k in ('admission_code','major_code','name','program_name'))
                    } | row
                    write(conn,'major_catalogue',record)
                    inserted += 1
            return Result({'inserted': inserted, 'skipped': skipped, 'total': inserted + skipped})
        raise ValueError('Unknown RPC')


def save_major(data, major_id=None):
    record = data | {'search_text': ' '.join(str(data[k]) for k in ('admission_code','major_code','name','program_name'))}
    if major_id:
        return (Query('major_catalogue').update(record | {'updated_at': now()}).eq('id',major_id).execute().data or [None])[0]
    return Query('major_catalogue').insert(record).execute().data[0]
