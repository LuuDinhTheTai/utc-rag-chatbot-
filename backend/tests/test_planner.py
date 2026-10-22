from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.config import settings
from app.localdb import Database, connect
from app.main import app
from app.security import password_hash


@pytest.fixture
def planner(monkeypatch):
    monkeypatch.setenv('RATE_LIMIT_LOGIN','0')
    monkeypatch.setenv('RATE_LIMIT_GLOBAL','0')
    settings.cache_clear()
    with connect() as conn:
        for role in ('admin','student'):
            conn.execute('INSERT INTO accounts VALUES (?,?,?,?,?,1,?,?)',(str(uuid4()),role+'@test.com',role,password_hash('test-password-for-planner'),role,'t','t'))
    with TestClient(app) as client:
        headers={}
        for role in ('admin','student'):
            login=client.post('/auth/login',json={'email':role+'@test.com','password':'test-password-for-planner'})
            assert login.status_code==200
            headers[role]={'Authorization':'Bearer '+login.json()['token']}
        majors=[]
        for i in range(2):
            majors.append(Database().rpc('save_major',{'p_data':dict(admission_code=f'GHA0{i}',major_code='7520201',name='Engineering',program_name=f'Program {i}',admission_year=2026,campus='hanoi',quota=100,methods=['PT1'],subject_groups=['A00'],notes='',source_url='https://utc.edu.vn/',is_active=True)}).execute().data)
        yield client,headers,majors


def rule_body():
    return dict(title='Test-only reviewed formula',admission_year=2026,campus='hanoi',subject_group='A00',subjects=['Toán','Vật lý','Hóa học'],weights=[1,1,1],priority_mode='taper_30',priority_cap=2.75,bonus_cap=3,source_url='https://utc.edu.vn/test-only-rule',scope_note='Fixture only, not an actual regulation.',source_reviewed=True)


def test_manual_calculation(planner):
    client,_,_=planner
    result=client.post('/score-calculations',json=dict(year=2026,campus='hanoi',scores=[7.25,8,9],priority=1,bonus=.5))
    assert result.status_code==200,result.text
    data=result.json()
    assert data['total']=='25.75' and data['base']=='24.25'
    assert data['mode']=='manual' and data['rule'] is None
    assert client.post('/score-calculations',json=dict(year=2026,campus='hanoi',scores=[10,10,10],priority=5,bonus=3)).json()['total']=='30.00'
    for scores in ([11,2,3],[-1,2,3],[1,2],['NaN',2,3]):
        assert client.post('/score-calculations',json=dict(year=2026,campus='hanoi',scores=scores)).status_code==422


@pytest.mark.parametrize('scores,priority',[([7.5,7.5,7.5],'2.00'),([9,9,9],'0.80'),([10,10,10],'0.00')])
def test_formula_taper_and_scope(planner,scores,priority):
    client,headers,_=planner
    response=client.post('/admin/score-rules',headers=headers['admin'],json=rule_body())
    assert response.status_code==201,response.text
    rule=response.json()
    data=dict(year=2026,campus='hanoi',scores=scores,priority=2,rule_id=rule['id'])
    result=client.post('/score-calculations',json=data)
    assert result.status_code==200,result.text
    assert result.json()['priority_applied']==priority
    assert result.json()['rule']['source_url']==rule['source_url']
    for change in ({'year':2025},{'campus':'hcm'},{'priority':3}):
        assert client.post('/score-calculations',json=data|change).status_code==422


def test_rules_permissions_review_and_revocation(planner):
    client,headers,_=planner
    assert client.post('/admin/score-rules',headers=headers['student'],json=rule_body()).status_code==403
    assert client.post('/admin/score-rules',json=rule_body()).status_code==401
    for change in ({'source_reviewed':False},{'source_url':'https://evil.test'},{'weights':[0,1,1]}):
        assert client.post('/admin/score-rules',headers=headers['admin'],json=rule_body()|change).status_code==422
    response=client.post('/admin/score-rules',headers=headers['admin'],json=rule_body()|{'weights':[2,1,1]})
    assert response.status_code==201,response.text
    rule=response.json()
    result=client.post('/score-calculations',json=dict(year=2026,campus='hanoi',scores=[9,8,7],rule_id=rule['id'])).json()
    assert result['base']=='24.75'
    assert client.delete('/admin/score-rules/'+rule['id'],headers=headers['admin']).status_code==200
    assert client.get('/score-rules').json()==[]
    assert client.post('/score-calculations',json=dict(year=2026,campus='hanoi',scores=[9,8,7],rule_id=rule['id'])).status_code==404


def test_preferences_order_conflicts_and_ownership(planner):
    client,headers,majors=planner
    assert client.get('/planner/preferences').status_code==401
    added=[]
    for revision,major in enumerate(majors):
        response=client.post('/planner/preferences',headers=headers['student'],json={'offering_id':major['id'],'revision':revision})
        assert response.status_code==201,response.text
        added.append(response.json()['id'])
    assert client.get('/planner/preferences',headers=headers['admin']).json()['items']==[]
    assert client.post('/planner/preferences',headers=headers['student'],json={'offering_id':majors[0]['id'],'revision':2}).status_code==409
    assert client.get('/planner/preferences',headers=headers['student']).json()['revision']==2
    assert client.post('/planner/preferences/reorder',headers=headers['student'],json={'year':2026,'revision':2,'ids':added[::-1]}).status_code==200
    result=client.get('/planner/preferences',headers=headers['student']).json()
    assert [p['id'] for p in result['items']]==added[::-1] and result['revision']==3
    assert client.post('/planner/preferences/reorder',headers=headers['student'],json={'year':2026,'revision':2,'ids':added}).status_code==409
    assert client.post('/planner/preferences/reorder',headers=headers['student'],json={'year':2026,'revision':3,'ids':[added[0]]}).status_code==422
    assert client.delete('/planner/preferences/'+added[0]+'?revision=0',headers=headers['admin']).status_code==404
    patch={'revision':3,'method':'PT1','estimated_score':31,'score_scale':30}
    assert client.patch('/planner/preferences/'+added[0],headers=headers['student'],json=patch).status_code==422
    assert client.patch('/planner/preferences/'+added[0],headers=headers['student'],json=patch|{'estimated_score':25}).status_code==200
    Database().table('major_catalogue').delete().eq('id',majors[0]['id']).execute()
    result=client.get('/planner/preferences',headers=headers['student']).json()
    assert len(result['items'])==2 and next(p for p in result['items'] if p['id']==added[0])['available'] is False
    assert client.delete('/planner/preferences/'+added[0]+'?revision=4',headers=headers['student']).status_code==200


def test_checklist_templates_ownership_and_calendar(planner):
    client,headers,_=planner
    assert client.get('/planner/checklist').status_code==401
    assert client.post('/planner/checklist/templates',headers=headers['student'],json={'year':2026}).json()['inserted']==5
    assert client.post('/planner/checklist/templates',headers=headers['student'],json={'year':2026}).json()['inserted']==0
    tasks=client.get('/planner/checklist',headers=headers['student']).json()
    assert all(t['due_date'] is None for t in tasks)
    new=client.post('/planner/checklist',headers=headers['student'],json=dict(admission_year=2026,title='Nhắc; việc, riêng\nKhông chèn ICS',description='Tiếng Việt '*20,due_date='2026-07-20',source_url='https://utc.edu.vn/notice'))
    assert new.status_code==201,new.text
    identifier=new.json()['id']
    assert client.patch('/planner/checklist/'+identifier,headers=headers['admin'],json={'completed':True}).status_code==404
    assert client.delete('/planner/checklist/'+identifier,headers=headers['admin']).status_code==404
    assert client.patch('/planner/checklist/'+identifier,headers=headers['student'],json={'source_url':'javascript:alert(1)'}).status_code==422
    calendar=client.get('/planner/calendar',headers=headers['student']).json()
    assert calendar['events']==1
    assert 'DTSTART;VALUE=DATE:20260720' in calendar['content'] and 'DTEND;VALUE=DATE:20260721' in calendar['content']
    assert 'SUMMARY:Nhắc\\; việc\\, riêng\\nKhông chèn ICS' in calendar['content']
    assert all(len(line.encode())<=75 for line in calendar['content'].split('\r\n'))
    assert client.get('/planner/calendar',headers=headers['admin']).json()['events']==0
    assert client.patch('/planner/checklist/'+identifier,headers=headers['student'],json={'completed':True}).status_code==200
    assert client.get('/planner/calendar',headers=headers['student']).json()['events']==0
    assert client.patch('/planner/checklist/'+identifier,headers=headers['student'],json={'due_date':None,'completed':False}).status_code==200
    assert client.delete('/planner/checklist/'+identifier,headers=headers['student']).status_code==200


def test_additive_migration_repeatability(planner):
    _,_,majors=planner
    for _ in range(3):
        with connect() as conn:
            assert conn.execute("SELECT count(*) FROM schema_migrations WHERE version='planner_v1'").fetchone()[0]==1
            assert conn.execute('SELECT count(*) FROM major_catalogue').fetchone()[0]==len(majors)
            assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_upgrade_existing_v2_is_additive(tmp_path):
    from contextlib import closing
    from app.migrations import initialize,open_db
    with closing(open_db(tmp_path/'utc.sqlite3')) as conn:
        initialize(conn)
        conn.execute("INSERT INTO accounts VALUES ('existing','existing@test.com','','hash','student',1,'t','t')")
        conn.execute("INSERT INTO chat_sessions VALUES ('old-session','old-hash','existing','t')")
        conn.commit()
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='planner_tasks'").fetchone()
    with connect() as conn:
        assert conn.execute('SELECT count(*) FROM planner_tasks').fetchone()[0]==0
        assert conn.execute('SELECT token_hash FROM chat_sessions').fetchone()[0]=='old-hash'
        assert conn.execute('SELECT password_hash FROM accounts').fetchone()[0]=='hash'
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_failed_additive_upgrade_rolls_back(tmp_path,monkeypatch):
    import sqlite3
    from contextlib import closing
    from pathlib import Path
    from app.migrations import initialize,open_db
    with closing(open_db(tmp_path/'utc.sqlite3')) as conn:
        initialize(conn)
    original=Path.read_text
    def broken(path,*args,**kwargs):
        if path.name=='planner.sql':
            return 'CREATE TABLE partially_created(id TEXT);\nTHIS IS INVALID SQL;\n'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',broken)
    with pytest.raises(sqlite3.OperationalError):
        connect()
    with closing(open_db(tmp_path/'utc.sqlite3')) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='partially_created'").fetchone()
        assert not conn.execute("SELECT 1 FROM schema_migrations WHERE version='planner_v1'").fetchone()
        assert conn.execute("SELECT 1 FROM schema_migrations WHERE version='schema_v2'").fetchone()


def test_task_dates_are_bounded(planner):
    client,headers,_=planner
    for day in ('9999-12-31','1900-01-01','2026-02-30'):
        assert client.post('/planner/checklist',headers=headers['student'],json={'admission_year':2026,'title':'Invalid date','due_date':day}).status_code==422


def test_saved_snapshot_detects_changed_program_identity(planner):
    client,headers,majors=planner
    added=client.post('/planner/preferences',headers=headers['student'],json={'offering_id':majors[0]['id'],'revision':0})
    assert added.status_code==201
    with connect() as conn:
        conn.execute('UPDATE admission_offerings SET admission_code=? WHERE id=?',('NEWCODE',majors[0]['id']))
    saved=client.get('/planner/preferences',headers=headers['student']).json()['items'][0]
    assert saved['available'] is False
    assert saved['admission_code']==majors[0]['admission_code']
