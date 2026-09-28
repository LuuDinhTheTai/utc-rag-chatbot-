import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from postgrest.exceptions import APIError

from app.main import app
from app.majors import MajorInput, make_router, parse_catalogue

BODY = dict(admission_code='GHA01',major_code='7220201',name='English',program_name='English program',
            admission_year=2026,campus='hanoi',quota=60,methods=['PT1'],subject_groups=['D01'],
            notes='',source_url='https://utc.edu.vn/',is_active=True)
ID='00000000-0000-0000-0000-000000000001'

@pytest.fixture
def catalogue():
    fake=MagicMock()
    query=MagicMock()
    for name in ['select','eq','ilike','order','range','insert','update','delete','upsert']:
        getattr(query,name).return_value=query
    fake.table.return_value=query
    fake.rpc.return_value.execute.return_value.data=dict(BODY,id=ID)
    query.execute.return_value=SimpleNamespace(data=[dict(BODY,id=ID)],count=1)
    test_app=FastAPI()
    test_app.include_router(make_router(lambda:fake, lambda:'admin'))
    return TestClient(test_app),fake,query

@pytest.mark.parametrize('method,path,body',[
    ('post','/admin/majors',BODY),
    ('patch','/admin/majors/'+ID,BODY),
    ('delete','/admin/majors/'+ID,None),
    ('get','/admin/majors',None),
])
def test_admin_routes_require_auth(method,path,body):
    with TestClient(app) as client:
        response=client.request(method,path,json=body)
    assert response.status_code==401

def test_public_list_hides_inactive_and_paginates(catalogue):
    client,fake,query=catalogue
    response=client.get('/majors?year=2026&campus=hanoi&page=2&page_size=12&q=English')
    assert response.status_code==200
    query.eq.assert_any_call('is_active',True)
    query.eq.assert_any_call('campus','hanoi')
    query.range.assert_called_once_with(12,23)
    query.ilike.assert_called_once_with('search_text','%English%')

def test_public_detail_hides_inactive(catalogue):
    client,fake,query=catalogue
    query.execute.return_value.data=[]
    assert client.get('/majors/'+ID).status_code==404
    query.eq.assert_any_call('is_active',True)

def test_crud(catalogue):
    client,fake,query=catalogue
    assert client.post('/admin/majors',json=BODY).status_code==201
    assert fake.rpc.call_args.args[0]=='save_major'
    assert fake.rpc.call_args.args[1]['p_data']['admission_code']=='GHA01'
    assert client.patch('/admin/majors/'+ID,json={**BODY,'quota':70}).status_code==200
    assert fake.rpc.call_args.args[1]['p_data']['quota']==70
    assert fake.rpc.call_args.args[1]['p_id']==ID
    fake.rpc.return_value.execute.return_value.data=True
    assert client.delete('/admin/majors/'+ID).json()=={'deleted':True}

def test_duplicate_is_conflict(catalogue):
    client,fake,query=catalogue
    fake.rpc.return_value.execute.side_effect=APIError({'code':'23505','message':'duplicate','details':None,'hint':None})
    assert client.post('/admin/majors',json=BODY).status_code==409

@pytest.mark.parametrize('field,value',[('quota',-1),('admission_year',1999),('name',' '),('campus','other'),('source_url','javascript:alert(1)'),('subject_groups',['INVALID,VALUE'])])
def test_invalid_major_rejected(field,value):
    with pytest.raises(ValidationError):
        MajorInput(**{**BODY,field:value})

def source_json():
    return {'metadata':{'source_url':'https://utc.edu.vn/'},'chi_tieu_2026':{'GHA':{'programs':[{
        'ma_xet_tuyen':'GHA01','ma_nganh':'7220201','ten_nganh':'English',
        'ten_chuong_trinh_nganh':'English program','chi_tieu_du_kien':None,
        'phuong_thuc_tuyen_sinh':['PT1'],'to_hop_mon_pt1_pt2':['D01'],'ghi_chu':None
    }]}}}

def test_import_maps_year_campus_and_unknown_quota():
    row=parse_catalogue(source_json())[0]
    assert row['admission_year']==2026 and row['campus']=='hanoi'
    assert row['quota'] is None and row['notes']==''

def test_import_duplicate_in_file_rejected():
    data=source_json()
    data['chi_tieu_2026']['GHA']['programs']*=2
    with pytest.raises(ValueError):
        parse_catalogue(data)

def test_import_never_overwrites_existing(catalogue):
    client,fake,query=catalogue
    fake.rpc.return_value.execute.return_value.data={'inserted':0,'skipped':1,'total':1}
    response=client.post('/admin/majors/import',files={'file':('majors.json',json.dumps(source_json()),'application/json')})
    assert response.json()=={'inserted':0,'skipped':1,'total':1}
    assert fake.rpc.call_args.args[0]=='import_majors'

def test_bad_import_does_not_write(catalogue):
    client,fake,query=catalogue
    response=client.post('/admin/majors/import',files={'file':('majors.json','{','application/json')})
    assert response.status_code==422
    fake.table.assert_not_called()

def test_pagination_bounds(catalogue):
    client,_,_=catalogue
    assert client.get('/majors?page=0').status_code==422
    assert client.get('/majors?page_size=1001').status_code==422


def test_admission_codes_preserve_spaces():
    assert MajorInput(**{**BODY,'admission_code':'GHA23 TM'}).admission_code=='GHA23 TM'

def test_methods_accept_description():
    assert MajorInput(**{**BODY,'methods':['Separate admission notice']}).methods==['Separate admission notice']
