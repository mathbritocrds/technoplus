"""Employee identity stays linked across modules after a name change."""
import json

import pytest
from fastapi.testclient import TestClient

from app import main, employee_identity


@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB',str(tmp_path/'rename.db'))
    monkeypatch.setattr(main,'SUPABASE_DATABASE_URL','')
    with main.db() as c:
        c.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(c,main.MIGRATIONS)
    client=TestClient(main.app)
    response=client.post('/auth/register',json={'email':'rename-admin@example.test','password':'rename-test-password'})
    assert response.status_code==201,response.text
    return client,{'Authorization':'Bearer '+response.json()['token']}


def employee(service,name='Ana Lima',**extra):
    client,auth=service
    response=client.post('/employees',headers=auth,json={
        'name':name,'salary':3000,'pin':'1234','hired_on':'2024-01-01',**extra})
    assert response.status_code==201,response.text
    return response.json()['id']


def task(service,**values):
    client,auth=service
    response=client.post('/tasks',headers=auth,json={'title':'Tarefa de teste',**values})
    assert response.status_code==201,response.text
    return response.json()['id']


def worker(service,eid):
    client,auth=service
    email=f'employee-{eid}@example.test'
    assert client.post(f'/employees/{eid}/account',headers=auth,json={'email':email,'password':'worker-test-password'}).status_code==201
    response=client.post('/auth/employee/login',json={'email':email,'password':'worker-test-password'})
    assert response.status_code==200,response.text
    return {'Authorization':'Bearer '+response.json()['token']}


def test_rename_updates_tasks_departments_clock_portal_and_messages(service):
    client,auth=service;eid=employee(service);session=worker(service,eid)
    department=client.post('/departments',headers=auth,json={'name':'Produção','lead_employee_id':eid})
    assert department.status_code==201,department.text
    tid=task(service,assignee='ana lima',status=1)
    assert client.post('/messages',headers=session,json={'scope':'team','body':'Mensagem antes da alteração'}).status_code==201
    assert client.patch(f'/employees/{eid}',headers=auth,json={'name':'  Ana Torres  '}).status_code==200
    saved=client.get('/tasks',headers=auth).json()[0]
    assert saved['assignee']=='Ana Torres' and saved['assignee_employee_id']==eid
    assert [item['id'] for item in client.get('/employee/tasks',headers=session).json()]==[tid]
    assert client.get('/employee/summary',headers=session).json()['employee']['name']=='Ana Torres'
    assert client.get('/departments',headers=auth).json()[0]['lead']=='Ana Torres'
    assert client.get('/clock/employees').json()[0]['name']=='Ana Torres'
    assert tid in [item['id'] for item in client.get(f'/clock/tasks?employee_id={eid}&pin=1234').json()]
    message=client.get('/messages',headers=auth).json()[0]
    assert message['sender_name']=='Ana Torres' and message['recorded_sender_name']=='Ana Lima'
    with main.db() as c:
        assert c.execute('SELECT sender_name FROM messages').fetchone()[0]=='Ana Lima'
    client.put('/settings/workplace',headers=auth,json={'lat':0,'lng':0,'radius_m':100})
    punch=client.post('/clock',json={'employee_id':eid,'pin':'1234','task_id':tid,'consent':True,'samples':[{'lat':0,'lng':0,'accuracy_m':10}]})
    assert punch.status_code==200,punch.text


def test_closed_payroll_and_finance_show_current_name_without_rewriting_history(service):
    client,auth=service;eid=employee(service);session=worker(service,eid)
    closed=client.post('/payroll/close',headers=auth,json={'month':'2026-10'})
    assert closed.status_code==200,closed.text
    salary=client.get('/finance?status=all',headers=auth).json()[0]
    assert client.patch(f"/finance/{salary['id']}/paid",headers=auth,json={}).status_code==200
    with main.db() as c:
        snapshot=c.execute('SELECT snapshot FROM payroll_items').fetchone()[0]
        journals=[tuple(row) for row in c.execute('SELECT id,description,payload_hash FROM ledger_journals ORDER BY id')]
        receipt=c.execute('SELECT description FROM payment_history').fetchone()[0]
    assert client.patch(f'/employees/{eid}',headers=auth,json={'name':'Ana Torres'}).status_code==200
    payroll=client.get('/payroll?month=2026-10',headers=auth).json()['employees'][0]
    assert payroll['name']=='Ana Torres' and payroll['recorded_name']=='Ana Lima'
    assert client.get('/employee/payroll?month=2026-10',headers=session).json()['name']=='Ana Torres'
    assert client.get('/payroll/annual-cost?year=2026',headers=auth).json()['employees'][0]['name']=='Ana Torres'
    finance=client.get('/finance?status=all&q=Ana%20Torres',headers=auth).json()
    assert len(finance)==1 and finance[0]['description'].endswith('Ana Torres')
    assert finance[0]['recorded_description'].endswith('Ana Lima')
    assert client.get('/finance/payments',headers=auth).json()[0]['description'].endswith('Ana Torres')
    report=client.get('/finance/dre?start=2026-10&end=2026-10',headers=auth).json()
    assert report['entries'][0]['description'].endswith('Ana Torres')
    with main.db() as c:
        assert c.execute('SELECT snapshot FROM payroll_items').fetchone()[0]==snapshot
        assert c.execute('SELECT description FROM payment_history').fetchone()[0]==receipt
        assert [tuple(row) for row in c.execute('SELECT id,description,payload_hash FROM ledger_journals ORDER BY id')]==journals


def test_homonyms_keep_separate_task_ownership_and_free_text_is_not_replaced(service):
    client,auth=service;first=employee(service);second=employee(service)
    first_task=task(service,assignee_employee_id=first)
    second_task=task(service,assignee_employee_id=second)
    external=task(service,assignee='Ana Lima Consultoria')
    ambiguous=task(service,assignee='Ana Lima')
    assert client.patch(f'/employees/{first}',headers=auth,json={'name':'Ana Torres'}).status_code==200
    tasks={row['id']:row for row in client.get('/tasks',headers=auth).json()}
    assert tasks[first_task]['assignee']=='Ana Torres'
    assert tasks[second_task]['assignee']=='Ana Lima' and tasks[second_task]['assignee_employee_id']==second
    assert tasks[external]['assignee']=='Ana Lima Consultoria'
    assert tasks[ambiguous]['assignee']=='Ana Lima' and tasks[ambiguous]['assignee_employee_id'] is None
    assert client.patch(f'/tasks/{first_task}',headers=auth,json={'assignee':'Ana Torres'}).status_code==200
    assert client.patch(f'/employees/{first}',headers=auth,json={'name':'Ana Silva'}).status_code==200
    assert client.get('/tasks',headers=auth).json()[0]['assignee']=='Ana Silva'


def test_legacy_links_can_be_recovered_from_frozen_employee_ids(service):
    client,auth=service;eid=employee(service)
    assert client.post('/payroll/close',headers=auth,json={'month':'2026-10'}).status_code==200
    with main.db() as c:
        tid=c.execute("INSERT INTO tasks(title,assignee,status) VALUES('Legado','Ana Lima',1) RETURNING id").fetchone()[0]
        c.execute("UPDATE employees SET name='Ana Torres' WHERE id=?",(eid,))
        c.execute("DELETE FROM settings WHERE k='employee_identity_v1'")
        employee_identity.link_legacy_references(c)
        saved=c.execute('SELECT assignee,assignee_employee_id FROM tasks WHERE id=?',(tid,)).fetchone()
        assert tuple(saved)==('Ana Torres',eid)
        assert json.loads(c.execute('SELECT snapshot FROM payroll_items').fetchone()[0])['name']=='Ana Lima'
        employee_identity.link_legacy_references(c)
        assert c.execute('SELECT COUNT(*) FROM employee_name_aliases WHERE employee_id=?',(eid,)).fetchone()[0]==1


def test_failed_rename_rolls_back_all_links(service):
    client,auth=service;eid=employee(service);tid=task(service,assignee='Ana Lima')
    response=client.patch(f'/employees/{eid}',headers=auth,json={'name':'Ana Torres','department_id':9999})
    assert response.status_code==404
    assert client.get('/employees',headers=auth).json()[0]['name']=='Ana Lima'
    assert client.get('/tasks',headers=auth).json()[0]['assignee']=='Ana Lima'
    with main.db() as c:
        assert c.execute('SELECT COUNT(*) FROM employee_name_aliases').fetchone()[0]==0


def test_task_reassignment_and_clear_use_stable_employee_ids(service):
    client,auth=service;first=employee(service);second=employee(service,'Bruno Souza')
    tid=task(service,assignee='Ana Lima')
    assert client.patch(f'/tasks/{tid}',headers=auth,json={'assignee_employee_id':second}).status_code==200
    saved=client.get('/tasks',headers=auth).json()[0]
    assert (saved['assignee'],saved['assignee_employee_id'])==('Bruno Souza',second)
    assert client.patch(f'/tasks/{tid}',headers=auth,json={'assignee_employee_id':None}).status_code==200
    saved=client.get('/tasks',headers=auth).json()[0]
    assert saved['assignee']=='' and saved['assignee_employee_id'] is None
