import json
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.legacydb import prepare
from app.localdb import Database, connect
from app.migrations import digest, migrate, open_db, rollback


@pytest.fixture
def legacy(tmp_path):
    with closing(open_db(tmp_path/'utc.sqlite3')) as conn:
        prepare(conn)
        conn.execute("INSERT INTO accounts VALUES ('a','a@example.com','Name','hash','admin',1,'t','t')")
        conn.execute("INSERT INTO auth_sessions VALUES ('auth','a','2099-01-01','t')")
        conn.execute("INSERT INTO chat_sessions VALUES ('s','chat','t','a')")
        conn.execute("INSERT INTO documents VALUES ('d','Title','https://utc.edu.vn',2026,'hanoi','admission','hash','Text','ready',1,NULL,'a','original.txt','original.txt',3,'t')")
        conn.execute("INSERT INTO document_chunks VALUES ('c','d',0,'Text','[1,0]')")
        source = {'id':'c','document_id':'d','title':'Title','content':'Text','citation':1,'extra':'keep'}
        conn.execute("INSERT INTO messages(id,session_id,role,content,sources,created_at) VALUES ('m','s','assistant','Answer',?,'t')", (json.dumps([source]),))
        conn.execute("INSERT INTO feedback VALUES ('f','m',1,'Useful','t')")
        conn.execute("INSERT INTO major_catalogue VALUES ('major','GHA01','7520201','Engineering','Engineering programme',2026,'hanoi',100,?,?,'','https://utc.edu.vn',1,'engineering','t','t')", (json.dumps(['PT1','Exam']),json.dumps(['D01','A00'])))
        conn.execute("INSERT INTO cutoff_scores VALUES (2026,'hanoi','GHA01','Published abbreviation','PT1',25,30,'https://utc.edu.vn','','engineering')")
        conn.commit()
    files = tmp_path/'files'
    files.mkdir()
    (files/'original.txt').write_bytes(b'pdf')
    return tmp_path


def test_dry_run_apply_repeat_and_rollback_preserve_data(legacy):
    path = legacy/'utc.sqlite3'
    original = path.read_bytes()
    kwargs = dict(embedding_model='verified-test-model',dimensions=2)
    assert migrate(legacy,**kwargs)['status'] == 'validated'
    assert path.read_bytes() == original
    result = migrate(legacy,apply=True,offline=True,**kwargs)
    assert result['status'] == 'migrated'
    assert (legacy/'files/original.txt').read_bytes() == b'pdf'
    assert migrate(legacy,apply=True,offline=True)['status'] == 'already_v2'
    with closing(open_db(path)) as conn:
        assert conn.execute('SELECT program_name_snapshot FROM cutoff_scores').fetchone()[0] == 'Published abbreviation'
        assert conn.execute('SELECT program_name FROM admission_offerings').fetchone()[0] == 'Engineering programme'
        assert conn.execute('SELECT model_name FROM embedding_models').fetchone()[0] == 'verified-test-model'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    assert rollback(legacy,result['backup'],offline=True)['status'] == 'rolled_back'
    with closing(open_db(path)) as conn:
        assert conn.execute('SELECT embedding FROM document_chunks').fetchone()[0] == '[1,0]'
        assert conn.execute('SELECT password_hash FROM accounts').fetchone()[0] == 'hash'
    assert (legacy/'files/original.txt').read_bytes() == b'pdf'


@pytest.mark.parametrize('kwargs,match', [({},'explicitly verified'), ({'embedding_model':'model','dimensions':3},'embedding')])
def test_invalid_model_does_not_change_source(legacy,kwargs,match):
    original = (legacy/'utc.sqlite3').read_bytes()
    with pytest.raises((ValueError,sqlite3.IntegrityError),match=match):
        migrate(legacy,apply=True,offline=True,**kwargs)
    assert (legacy/'utc.sqlite3').read_bytes() == original


def test_rollback_refuses_new_writes(legacy):
    result = migrate(legacy,apply=True,offline=True,embedding_model='model',dimensions=2)
    with closing(open_db(legacy/'utc.sqlite3')) as conn:
        conn.execute("UPDATE messages SET content='New answer'")
        conn.commit()
    with pytest.raises(ValueError,match='lose new data'):
        rollback(legacy,result['backup'],offline=True)


def test_migrated_api_contract_and_atomic_composite_write(legacy,monkeypatch):
    migrate(legacy,apply=True,offline=True,embedding_model='verified-test-model',dimensions=2)
    monkeypatch.setenv('EMBEDDING_MODEL','verified-test-model')
    monkeypatch.setenv('EMBEDDING_DIMENSIONS','2')
    settings.cache_clear()
    with TestClient(main.app) as client:
        assert client.get('/majors').json()['items'][0]['methods'] == ['PT1','Exam']
        assert client.get('/majors').json()['items'][0]['subject_groups'] == ['D01','A00']
        assert client.get('/cutoffs').json()['items'][0]['program_name'] == 'Published abbreviation'
    db = Database()
    message = db.table('messages').select('*').eq('id','m').execute().data[0]
    assert message['sources'][0]['extra'] == 'keep'
    with pytest.raises(sqlite3.IntegrityError):
        db.table('messages').insert([
            {'session_id':'s','role':'user','content':'Should roll back'},
            {'session_id':'missing','role':'assistant','content':'Invalid'},
        ]).execute()
    assert len(db.table('messages').select('*').execute().data) == 1
    matches = db.rpc('match_chunks',dict(query_embedding=[1,0],filter_year=2026,filter_campus='hanoi',min_similarity=.5,match_count=6)).execute().data
    assert matches[0]['id'] == 'c'
    monkeypatch.setenv('EMBEDDING_MODEL','different-model')
    settings.cache_clear()
    assert db.rpc('match_chunks',dict(query_embedding=[1,0],filter_year=2026,filter_campus='hanoi',min_similarity=.5,match_count=6)).execute().data == []
    db.table('documents').delete().eq('id','d').execute()
    assert db.table('messages').select('*').eq('id','m').execute().data[0]['sources'] == message['sources']
    with connect() as conn:
        assert conn.execute('SELECT chunk_id FROM message_citations').fetchone()[0] is None


def test_legacy_runtime_requires_explicit_migration(legacy):
    with pytest.raises(RuntimeError,match='Legacy database'):
        connect()
    with pytest.raises(ValueError,match='offline'):
        migrate(legacy,apply=True)


def test_unknown_tables_are_not_silently_discarded(legacy):
    with closing(open_db(legacy/'utc.sqlite3')) as conn:
        conn.execute('CREATE TABLE plugin_data(id TEXT)')
        conn.commit()
    with pytest.raises(ValueError,match='Unrecognized tables'):
        migrate(legacy)


def test_rollback_refuses_wal_writes(legacy):
    result = migrate(legacy,apply=True,offline=True,embedding_model='model',dimensions=2)
    with closing(open_db(legacy/'utc.sqlite3')) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute("UPDATE messages SET content='New WAL answer'")
        conn.commit()
        with pytest.raises(ValueError,match='lose new data'):
            rollback(legacy,result['backup'],offline=True)


def test_backup_tampering_blocks_rollback(legacy):
    result = migrate(legacy,apply=True,offline=True,embedding_model='model',dimensions=2)
    from pathlib import Path
    with closing(open_db(Path(result['backup'])/'utc.sqlite3')) as conn:
        conn.execute("UPDATE messages SET content='Modified backup'")
        conn.commit()
    with pytest.raises(ValueError,match='Backup content changed'):
        rollback(legacy,result['backup'],offline=True)


def test_deleting_account_revokes_owned_chat_tokens(legacy):
    migrate(legacy,apply=True,offline=True,embedding_model='model',dimensions=2)
    with connect() as conn:
        conn.execute("DELETE FROM accounts WHERE id='a'")
    with connect() as conn:
        row = conn.execute("SELECT account_id,token_hash FROM chat_sessions WHERE id='s'").fetchone()
        assert row['account_id'] is None
        assert row['token_hash'] != 'chat'
        assert conn.execute('SELECT count(*) FROM auth_sessions').fetchone()[0] == 0
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
