from contextlib import closing
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app import main,rag
from app.config import settings
from app.localdb import connect,Database
from app.security import password_hash

@pytest.fixture
def library(monkeypatch):
    for key,value in [('RATE_LIMIT_GLOBAL','0'),('RATE_LIMIT_LOGIN','0'),('GOOGLE_API_KEY','test-only')]:monkeypatch.setenv(key,value)
    settings.cache_clear()
    with connect() as conn:
        for name,role in [('first','student'),('second','lecturer'),('root','admin')]:
            conn.execute('INSERT INTO accounts VALUES (?,?,?,?,?,1,?,?)',(str(uuid4()),name+'@test.com',name,password_hash('test-password-for-conversations'),role,'t','t'))
    monkeypatch.setattr(main,'match_chunks',lambda *args:[])
    monkeypatch.setattr(main,'embeddings',lambda:object())
    monkeypatch.setattr(main,'resolve_question',lambda question,*args:rag.ResolvedQuestion(question=question))
    with TestClient(main.app) as client:
        headers={}
        for name in ('first','second','root'):
            login=client.post('/auth/login',json={'email':name+'@test.com','password':'test-password-for-conversations'})
            assert login.status_code==200
            headers[name]={'Authorization':'Bearer '+login.json()['token']}
        yield client,headers

def seed(client,headers,question='Điểm chuẩn ngành công nghệ thông tin?',answer='Đại học Giao thông Vận tải tại Hà Nội.'):
    session=client.post('/sessions',headers=headers).json()
    rows=Database().table('messages').insert([{'session_id':session['id'],'role':'user','content':question},{'session_id':session['id'],'role':'assistant','content':answer,'sources':[]}]).execute().data
    return session,rows

def test_search_rename_and_index_updates(library):
    client,h=library
    s,rows=seed(client,h['first']);seed(client,h['second'],question='Bí mật tài khoản khác',answer='nội dung bí mật')
    assert client.get('/conversations').status_code==401
    assert client.get('/conversations',headers=h['first'],params={'q':'từ '*13}).status_code==422
    listing=client.get('/conversations',headers=h['first']).json()
    assert listing['total']==1 and listing['items'][0]['title'].startswith('Điểm chuẩn')
    assert not any('token' in key for key in listing['items'][0])
    for q in ('diem chuan','ĐIỂM CHUẨN','dai hoc giao thong','công nghệ'):
        assert client.get('/conversations',headers=h['first'],params={'q':q}).json()['total']==1,q
    for q in ('bi mat','%','" OR *'):
        result=client.get('/conversations',headers=h['first'],params={'q':q})
        assert result.status_code==200 and result.json()['total']==0
    renamed=client.patch('/conversations/'+s['id'],headers=h['first'],json={'title':'  Kế hoạch   tuyển sinh  '})
    assert renamed.status_code==200 and renamed.json()['title']=='Kế hoạch tuyển sinh'
    assert client.get('/conversations',headers=h['first'],params={'q':'ke hoach'}).json()['total']==1
    Database().table('messages').insert({'session_id':s['id'],'role':'user','content':'Câu hỏi mới'}).execute()
    assert client.get('/conversations/'+s['id'],headers=h['first']).json()['title']=='Kế hoạch tuyển sinh'
    Database().table('messages').update({'content':'Học phí chương trình quốc tế'}).eq('id',rows[1]['id']).execute()
    assert client.get('/conversations',headers=h['first'],params={'q':'hoc phi'}).json()['total']==1
    assert client.get('/conversations',headers=h['first'],params={'q':'dai hoc giao thong'}).json()['total']==0
    assert client.patch('/conversations/'+s['id'],headers=h['first'],json={'title':'   '}).status_code==422

def test_resume_bookmarks_and_privacy_across_roles(library):
    client,h=library;s,rows=seed(client,h['first']);answer=rows[1]['id']
    for name in ('second','root'):
        for path in ('/conversations/'+s['id'],'/conversations/'+s['id']+'/messages'):
            assert client.get(path,headers=h[name]).status_code==404
        assert client.patch('/conversations/'+s['id'],headers=h[name],json={'title':'Stolen'}).status_code==404
        assert client.delete('/conversations/'+s['id'],headers=h[name]).status_code==404
        assert client.post('/conversations/bookmarks/'+answer,headers=h[name]).status_code==404
        assert client.get('/messages',headers=h[name]|{'X-Conversation-Id':s['id']}).status_code==404
    assert client.get('/messages',headers={'X-Conversation-Id':s['id']}).status_code==401
    resumed=h['first']|{'X-Conversation-Id':s['id']}
    assert len(client.get('/messages',headers=resumed).json())==2
    assert client.post('/chat',headers=resumed,json={'question':'Có những phương thức nào?'}).status_code==200
    assert client.post('/conversations/bookmarks/'+rows[0]['id'],headers=h['first']).status_code==404
    for _ in range(2):assert client.post('/conversations/bookmarks/'+answer,headers=h['first']).json()['bookmarked'] is True
    saved=client.get('/conversations/bookmarks',headers=h['first'],params={'q':'dai hoc'}).json()
    assert saved['total']==1 and saved['items'][0]['conversation_id']==s['id']
    assert client.get('/conversations/bookmarks',headers=h['second']).json()['total']==0
    page=client.get('/conversations/'+s['id']+'/messages',headers=h['first']).json()
    assert next(m for m in page['items'] if m['id']==answer)['bookmarked'] is True
    assert client.delete('/conversations/bookmarks/'+answer,headers=h['first']).json()['bookmarked'] is False
    assert client.get('/conversations/bookmarks',headers=h['first']).json()['total']==0

def test_pagination_and_old_search_jump(library):
    client,h=library;s=client.post('/sessions',headers=h['first']).json()
    records=Database().table('messages').insert([{'session_id':s['id'],'role':'assistant' if i%2 else 'user','content':f'Message number {i:03d}','created_at':'2026-01-01T00:00:00+00:00'} for i in range(125)]).execute().data
    url='/conversations/'+s['id']+'/messages'
    latest=client.get(url,headers=h['first']).json()
    assert [m['content'] for m in latest['items']]==[r['content'] for r in records[-50:]]
    older=client.get(url,headers=h['first'],params={'before':latest['next_before']}).json()
    assert older['items'][-1]['content']=='Message number 074'
    oldest=client.get(url,headers=h['first'],params={'before':older['next_before']}).json()
    assert len(oldest['items'])==25 and oldest['next_before'] is None
    around=client.get(url,headers=h['first'],params={'around':records[30]['id']}).json()
    assert any(m['id']==records[30]['id'] for m in around['items'])
    assert around['next_before'] and around['next_after']
    following=client.get(url,headers=h['first'],params={'after':around['next_after']}).json()
    assert following['items'][0]['content']=='Message number 055'
    _,foreign=seed(client,h['second'])
    assert client.get(url,headers=h['first'],params={'around':foreign[0]['id']}).status_code==404
    assert client.get(url,headers=h['first'],params={'before':records[0]['id'],'after':records[1]['id']}).status_code==422

def test_delete_cascades_and_guest_is_not_claimed(library):
    client,h=library;s,rows=seed(client,h['first'])
    client.post('/conversations/bookmarks/'+rows[1]['id'],headers=h['first'])
    guest,_=seed(client,{},question='Khách cần tìm học phí?')
    assert client.get('/conversations/'+guest['id'],headers=h['first']).status_code==404
    assert client.get('/messages',headers={'X-Session-Token':guest['token']}).status_code==200
    assert client.delete('/conversations/'+s['id'],headers=h['first']).status_code==200
    with connect() as conn:
        assert conn.execute('SELECT count(*) FROM messages WHERE session_id=?',(s['id'],)).fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM conversation_bookmarks').fetchone()[0]==0
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert client.get('/conversations',headers=h['first'],params={'q':'diem chuan'}).json()['total']==0

def test_migration_backfill_repeatability_and_fts_plan(tmp_path):
    from app.migrations import initialize,open_db
    from app.planner_schema import ensure_planner
    with closing(open_db(tmp_path/'utc.sqlite3')) as conn:
        initialize(conn);ensure_planner(conn)
        conn.execute("INSERT INTO chat_sessions VALUES ('legacy','hash',NULL,'2025-01-01')")
        conn.execute("INSERT INTO messages(id,session_id,role,content,created_at) VALUES ('m','legacy','user','Đăng ký xét tuyển','2025-01-02')")
        conn.commit()
    for _ in range(2):
        with connect() as conn:
            assert conn.execute('SELECT title FROM conversation_metadata').fetchone()[0]=='Đăng ký xét tuyển'
            assert conn.execute('SELECT count(*) FROM conversation_message_search WHERE conversation_message_search MATCH ?',('"dang"*',)).fetchone()[0]==1
            assert conn.execute("SELECT count(*) FROM schema_migrations WHERE version='conversations_v1'").fetchone()[0]==1
            conn.execute("INSERT INTO conversation_message_search(conversation_message_search) VALUES ('integrity-check')")
    with connect() as conn:
        plan=' '.join(str(tuple(row)) for row in conn.execute("EXPLAIN QUERY PLAN SELECT rowid FROM conversation_message_search WHERE conversation_message_search MATCH 'dang'"))
        assert 'VIRTUAL TABLE INDEX' in plan

def test_failed_backfill_ddl_rolls_back(tmp_path,monkeypatch):
    import sqlite3
    from pathlib import Path
    from app.migrations import initialize,open_db
    from app.planner_schema import ensure_planner
    with closing(open_db(tmp_path/'utc.sqlite3')) as conn:
        initialize(conn);ensure_planner(conn)
    original=Path.read_text
    def broken(path,*args,**kwargs):
        if path.name=='conversations.sql':return 'CREATE TABLE unfinished_history(id TEXT);\nINVALID SQL;\n'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',broken)
    with pytest.raises(sqlite3.OperationalError):connect()
    with closing(open_db(tmp_path/'utc.sqlite3')) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='unfinished_history'").fetchone()
        assert not conn.execute("SELECT 1 FROM schema_migrations WHERE version='conversations_v1'").fetchone()
        assert conn.execute("SELECT 1 FROM schema_migrations WHERE version='planner_v1'").fetchone()

def test_bookmark_database_constraint_and_atomic_index_rollback(library):
    import sqlite3
    client,h=library;s,rows=seed(client,h['first'])
    with connect() as conn:
        foreign=conn.execute("SELECT id FROM accounts WHERE email='second@test.com'").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('INSERT INTO conversation_bookmarks VALUES (?,?,?)',(rows[1]['id'],foreign,'t'))
    with pytest.raises(sqlite3.IntegrityError):
        Database().table('messages').insert([{'session_id':s['id'],'role':'user','content':'RollbackUniquelySearchable'},{'session_id':'missing','role':'assistant','content':'Broken'}]).execute()
    assert client.get('/conversations',headers=h['first'],params={'q':'RollbackUniquelySearchable'}).json()['total']==0
