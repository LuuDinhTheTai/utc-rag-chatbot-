"""Normalized writes and compatibility projections for the existing HTTP contract."""
import hashlib
import json
import sqlite3
from uuid import uuid4

from .config import settings


def model_id(name=None, dimensions=None):
    cfg = settings()
    return hashlib.sha256(f'google:{name or cfg.embedding_model}:{dimensions or cfg.embedding_dimensions}'.encode()).hexdigest()


def ensure_model(conn, name=None, dimensions=None):
    cfg = settings()
    key = model_id(name, dimensions)
    conn.execute('INSERT INTO embedding_models VALUES (?,?,?,?) ON CONFLICT DO NOTHING',
                 (key, 'google', name or cfg.embedding_model, dimensions or cfg.embedding_dimensions))
    return key


def relation(table):
    """Only fixed internal identifiers are accepted by Query; no user SQL here."""
    if table == 'major_catalogue':
        return '''(SELECT m.*,o.admission_year,o.campus_code AS campus,o.admission_code,o.program_name,
          (SELECT json_group_array(name) FROM
            (SELECT CASE WHEN a.code IN ('PT1','PT2','PT3','PT4') THEN a.code ELSE a.name END AS name FROM offering_methods x JOIN admission_methods a ON a.code=x.method_code
             WHERE x.offering_id=m.id ORDER BY x.sort_order,x.method_code)) AS methods,
          (SELECT json_group_array(group_code) FROM
            (SELECT group_code FROM offering_subject_groups WHERE offering_id=m.id ORDER BY sort_order,group_code)) AS subject_groups
          FROM major_catalogue m JOIN admission_offerings o ON o.id=m.id)'''
    if table == 'documents':
        return '''(SELECT d.*,d.campus_code AS campus,
          (SELECT count(*) FROM document_chunks c WHERE c.document_id=d.id) AS chunk_count FROM documents d)'''
    if table == 'document_chunks':
        return f'''(SELECT c.*,e.vector AS embedding FROM document_chunks c LEFT JOIN chunk_embeddings e
          ON e.chunk_id=c.id AND e.model_id='{model_id()}')'''
    if table == 'messages':
        return '''(SELECT m.*,(SELECT json_group_array(json(source_snapshot)) FROM
          (SELECT source_snapshot FROM message_citations WHERE message_id=m.id ORDER BY citation)) AS sources FROM messages m)'''
    if table == 'cutoff_scores':
        return '''(SELECT c.*,o.admission_year,o.campus_code AS campus,o.admission_code,c.program_name_snapshot AS program_name,
          c.method_code AS method FROM cutoff_scores c JOIN admission_offerings o ON o.id=c.offering_id)'''
    return table


def insert_row(conn, table, record):
    columns = list(record)
    conn.execute(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', list(record.values()))


def method_code(conn, label):
    # Do not infer PT1..PT4 from free-text descriptions. Preserve labels exactly.
    row = conn.execute('SELECT code FROM admission_methods WHERE code=? AND name=?', (label,label)).fetchone()
    if label in ('PT1','PT2','PT3','PT4'):
        return label
    code = row[0] if row else 'label-' + hashlib.sha256(label.encode()).hexdigest()
    conn.execute('INSERT INTO admission_methods(code,name) VALUES (?,?) ON CONFLICT(code) DO NOTHING', (code,label))
    return code


def offering(conn, record, preferred_id=None, *, allow_name_variation=False):
    key = (record['admission_year'],record['campus'],record['admission_code'])
    row = conn.execute('SELECT id,program_name FROM admission_offerings WHERE admission_year=? AND campus_code=? AND admission_code=?',key).fetchone()
    if row:
        if row['program_name'] != record['program_name'] and not allow_name_variation:
            raise ValueError('Conflicting program names for one admission offering')
        return row['id']
    key_id = preferred_id or str(uuid4())
    conn.execute('INSERT INTO admission_offerings VALUES (?,?,?,?,?)', (key_id,*key,record['program_name']))
    return key_id


def write(conn, table, record, *, update=False):
    record = dict(record)
    identifier = record['id']
    if table == 'major_catalogue':
        if update:
            previous = conn.execute('SELECT admission_year,campus_code,admission_code FROM admission_offerings WHERE id=?', (identifier,)).fetchone()
            identity = (record['admission_year'],record['campus'],record['admission_code'])
            if tuple(previous) != identity and conn.execute('SELECT 1 FROM cutoff_scores WHERE offering_id=?', (identifier,)).fetchone():
                raise sqlite3.IntegrityError('Cannot move an offering with historical cutoffs; create a new offering')
            conn.execute('UPDATE admission_offerings SET admission_year=?,campus_code=?,admission_code=?,program_name=? WHERE id=?',
                         (record['admission_year'],record['campus'],record['admission_code'],record['program_name'],identifier))
        else:
            actual = offering(conn, record, identifier, allow_name_variation=True)
            # Catalogue supplies the canonical name; cutoff snapshots remain unchanged.
            conn.execute("UPDATE admission_offerings SET program_name=? WHERE id=?", (record["program_name"],actual))
            identifier = record['id'] = actual
        for key in ('admission_year','campus','admission_code','program_name'):
            record.pop(key)
        methods, groups = record.pop('methods', []), record.pop('subject_groups', [])
        save_base(conn, table, record, update)
        for junction in ('offering_methods','offering_subject_groups'):
            conn.execute(f'DELETE FROM {junction} WHERE offering_id=?', (identifier,))
        for position,label in enumerate(dict.fromkeys(methods)):
            conn.execute('INSERT INTO offering_methods VALUES (?,?,?)', (identifier,method_code(conn,label),position))
        for position,code in enumerate(dict.fromkeys(groups)):
            conn.execute('INSERT INTO offering_subject_groups VALUES (?,?,?)', (identifier,code,position))
    elif table == 'documents':
        record['campus_code'] = record.pop('campus')
        record.pop('chunk_count',None)
        save_base(conn, table, record, update)
    elif table == 'document_chunks':
        vector = record.pop('embedding')
        save_base(conn, table, record, update)
        key = ensure_model(conn)
        conn.execute('INSERT INTO chunk_embeddings VALUES (?,?,?,?) ON CONFLICT(chunk_id,model_id) DO UPDATE SET vector=excluded.vector,created_at=excluded.created_at',
                     (identifier,key,json.dumps(vector,allow_nan=False),timestamp()))
    elif table == 'messages':
        sources = record.pop('sources',[])
        save_base(conn, table, record, update)
        conn.execute('DELETE FROM message_citations WHERE message_id=?', (identifier,))
        if sources and record['role'] != 'assistant':
            raise ValueError('Only assistant messages may contain citations')
        for position,source in enumerate(sources,1):
            chunk = source.get('id')
            if not conn.execute('SELECT 1 FROM document_chunks WHERE id=?',(chunk,)).fetchone():
                chunk = None
            conn.execute('INSERT INTO message_citations VALUES (?,?,?,?)',
                         (identifier,source.get('citation',position),chunk,json.dumps(source,ensure_ascii=False,allow_nan=False)))
    else:
        save_base(conn, table, record, update)
    return identifier


def timestamp():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def save_base(conn, table, record, update):
    if update:
        values = {k:v for k,v in record.items() if k != 'id'}
        conn.execute(f'UPDATE {table} SET '+','.join(f'{k}=?' for k in values)+' WHERE id=?',
                     [*values.values(),record['id']])
    else:
        insert_row(conn,table,record)


def import_cutoff_rows(conn, rows):
    inserted = 0
    for year,campus,code,name,method,score,scale,url,note,search in rows:
        key = offering(conn,dict(admission_year=year,campus=campus,admission_code=code,program_name=name),allow_name_variation=True)
        stamp = timestamp()
        cursor = conn.execute('INSERT INTO cutoff_scores VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(offering_id,method_code) DO NOTHING',
                             (key,method,score,scale,url,note,search,name,stamp,stamp))
        inserted += cursor.rowcount
    return {'inserted':inserted,'skipped':len(rows)-inserted,'total':len(rows)}
