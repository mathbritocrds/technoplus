"""Routing namespaces must agree with ASGI mounts and decoded URL paths."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def installation(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB',str(tmp_path/'real.db'))
    monkeypatch.setattr(main,'SUPABASE_DATABASE_URL','')
    monkeypatch.setenv('DEMO_DB_PATH',str(tmp_path/'demo.db'))
    monkeypatch.setattr(main,'_fails',{})
    with main.db() as connection:
        connection.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(connection,main.MIGRATIONS)


def production(client,base):
    response=client.post(base+'/auth/register',json={'email':'real@routing.example','password':'routing-test-password'})
    assert response.status_code==201,response.text
    auth={'Authorization':'Bearer '+response.json()['token']}
    employee=client.post(base+'/employees',headers=auth,json={'name':'Real routing employee','salary':1000,'pin':'1234'})
    assert employee.status_code==201,employee.text
    return auth


def page_context(response):
    assert response.status_code==200,response.text
    match=re.search(r'globalThis\.SIGI_CONTEXT\s*=\s*(\{[^<]*?\})\s*;',response.text)
    assert match,'Frontend needs server-authoritative routing metadata'
    return json.loads(match.group(1))


@pytest.mark.parametrize('base',['','/corp','/demo'])
@pytest.mark.parametrize('segment',['demo','%64emo'])
def test_demo_namespace_isolated_with_prefix_and_encoded_path(installation,base,segment):
    client=TestClient(main.app,root_path=base)
    real=production(client,base)
    demo_base=base+'/'+segment
    login=client.post(demo_base+'/auth/demo-login')
    assert login.status_code==200,login.text
    demo={'Authorization':'Bearer '+login.json()['token']}
    records=client.get(demo_base+'/employees',headers=demo)
    assert records.status_code==200,records.text
    assert len(records.json())==6
    assert 'Real routing employee' not in {row['name'] for row in records.json()}
    assert client.get(demo_base+'/employees',headers=real).status_code==401
    assert client.get(base+'/employees',headers=demo).status_code==401
    assert client.patch(demo_base+'/employees/1',headers=real,json={'salary':9999}).status_code==401
    real_records=client.get(base+'/employees',headers=real).json()
    assert [(row['name'],row['salary']) for row in real_records]==[('Real routing employee',1000)]


@pytest.mark.parametrize('base',['','/corp','/demo'])
def test_frontend_context_and_assets_resolve_mounted_application(installation,base):
    client=TestClient(main.app,root_path=base)
    real_page=client.get(base+'/')
    assert page_context(real_page)=={'basePath':base,'demo':False}
    demo_page=client.get(base+'/%64emo/')
    assert page_context(demo_page)=={'basePath':base,'demo':True}
    if base:
        assert f'src="{base}/business.js"' in demo_page.text
        assert f'src="{base}/corporate-controls.js"' in demo_page.text
        assert f'src="{base}/density.js"' in real_page.text
    assert client.get(base+'/business.js').status_code==200
    assert client.get(base+'/corporate-controls.js').status_code==200


@pytest.mark.parametrize('base',['/corp','/demo'])
def test_permission_matrix_not_bypassed_by_mount_prefix(installation,base):
    client=TestClient(main.app,root_path=base)
    owner=production(client,base)
    body={'email':'operator@routing.example','password':'routing-test-password','role':'operator'}
    assert client.post(base+'/auth/register',headers=owner,json=body).status_code==201
    login=client.post(base+'/auth/login',json={'email':body['email'],'password':body['password']})
    assert login.status_code==200
    operator={'Authorization':'Bearer '+login.json()['token']}
    response=client.get(base+'/messages',headers=operator)
    assert response.status_code==403
    assert 'permissão' in response.json()['detail']
