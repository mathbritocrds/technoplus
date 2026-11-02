"""The populated demonstration must never share production data or credentials."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def workspaces(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB',str(tmp_path/'production.db'))
    monkeypatch.setenv('DEMO_DB_PATH',str(tmp_path/'isolated-demo.db'))
    monkeypatch.setattr(main,'SUPABASE_DATABASE_URL','')
    with main.db() as c:
        c.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(c,main.MIGRATIONS)
    return TestClient(main.app)


def demo_auth(client):
    response=client.post('/demo/auth/demo-login')
    assert response.status_code==200,response.text
    return {'Authorization':'Bearer '+response.json()['token']}


def test_demo_is_populated_and_production_remains_empty(workspaces):
    client=workspaces;headers=demo_auth(client)
    staff=client.get('/demo/employees',headers=headers)
    assert staff.status_code==200 and len(staff.json())==6
    assert all(row['salary']>0 for row in staff.json())
    assert client.get('/demo/payroll',headers=headers).json()['total_company_cost']>0
    assert client.get('/demo/products',headers=headers).json()
    assert client.get('/demo/materials',headers=headers).json()
    assert client.get('/demo/tasks',headers=headers).json()
    assert client.get('/demo/departments',headers=headers).json()
    assert client.get('/demo/spaces',headers=headers).json()
    assert client.get('/demo/time-entries/verify',headers=headers).json()['ok']
    assert client.get('/auth/status').json()=={'setup_required':True}
    with main.db() as c:
        for table in ('employees','admins','transactions','tasks','ledger_journals'):
            assert c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0


def test_tokens_and_mutations_are_isolated_between_workspaces(workspaces):
    client=workspaces;demo=demo_auth(client)
    assert client.get('/employees',headers=demo).status_code==401
    assert client.patch('/demo/employees/1',headers=demo,json={'salary':9999}).status_code==200
    production=client.post('/auth/register',json={'email':'real@example.test','password':'production-password'}).json()
    auth={'Authorization':'Bearer '+production['token']}
    assert client.get('/demo/employees',headers=auth).status_code==401
    assert client.get('/employees',headers=auth).json()==[]
    assert client.get('/demo/employees',headers=demo).json()[0]['salary']==9999


def test_demo_seed_is_repeatable_and_external_notifications_are_disabled(workspaces,monkeypatch):
    client=workspaces;headers=demo_auth(client)
    first=client.get('/demo/employees',headers=headers).json()
    demo_auth(client)
    assert client.get('/demo/employees',headers=headers).json()==first
    monkeypatch.setattr(main,'urlopen',lambda *args,**kwargs:pytest.fail('Demo must not send external messages'))
    result=client.post('/demo/notifications/test',headers=headers,json={'message':'Demo test'})
    assert result.status_code==403
    assert 'desativados' in result.json()['detail']


def test_demo_cannot_use_production_database_path(workspaces,monkeypatch):
    monkeypatch.setenv('DEMO_DB_PATH',main.DB)
    with pytest.raises(RuntimeError,match='separado'):
        workspaces.post('/demo/auth/demo-login')


def test_demo_does_not_connect_to_production_postgres(workspaces,monkeypatch):
    monkeypatch.setattr(main,'SUPABASE_DATABASE_URL','postgresql://unavailable.example/production')
    monkeypatch.setattr(main,'connect_postgres',lambda *_:pytest.fail('Demo must not connect to production PostgreSQL'))
    auth=demo_auth(workspaces)
    assert workspaces.get('/demo/employees',headers=auth).status_code==200


def test_demo_rejects_alias_of_production_database(workspaces,monkeypatch,tmp_path):
    import os
    alias=tmp_path/'production-alias.db'
    os.link(main.DB,alias)
    monkeypatch.setenv('DEMO_DB_PATH',str(alias))
    with pytest.raises(RuntimeError,match='separado'):
        workspaces.post('/demo/auth/demo-login')
