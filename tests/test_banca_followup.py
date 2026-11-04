"""Regressions for the seven independently reproduced review findings."""
import pytest
from fastapi.testclient import TestClient
from app import main, employee_identity
from tests.test_employee_rename import service, employee, task, worker


def allocated_task(service,stock=10):
    client,auth=service
    material=client.post('/materials',headers=auth,json={
        'name':'Aço','unit':'kg','stock':10,'unit_cost':68}).json()['id']
    tid=task(service)
    assert client.post(f'/tasks/{tid}/materials',headers=auth,json={
        'material_id':material,'quantity':2}).status_code==201
    if stock!=10:
        with main.db() as c:
            c.execute('UPDATE materials SET stock=? WHERE id=?',(stock,material))
    return tid,material


def state(tid,material):
    with main.db() as c:
        return (tuple(c.execute('SELECT title,status,progress FROM tasks WHERE id=?',(tid,)).fetchone()),
                c.execute('SELECT stock FROM materials WHERE id=?',(material,)).fetchone()[0],
                c.execute('SELECT consumed_quantity FROM task_materials WHERE task_id=?',(tid,)).fetchone()[0],
                [tuple(row) for row in c.execute('SELECT action,details FROM task_history WHERE task_id=? ORDER BY id',(tid,))])


@pytest.mark.parametrize('invalid',[
    {'title':''},{'title':'   '},{'progress':101},{'department_id':9999},
    {'assignee_employee_id':9999},{'priority':'desconhecida'},
])
def test_combined_edit_rejects_all_changes_before_consuming_stock(service,invalid):
    client,auth=service;tid,material=allocated_task(service);before=state(tid,material)
    response=client.patch(f'/tasks/{tid}',headers=auth,json={'status':1,**invalid})
    assert response.status_code in (400,404,422),response.text
    assert state(tid,material)==before


def test_combined_edit_consumes_once_and_records_changes(service):
    client,auth=service;tid,material=allocated_task(service)
    payload={'title':'Montagem','status':1,'progress':20}
    for _ in range(2):
        assert client.patch(f'/tasks/{tid}',headers=auth,json=payload).status_code==200
    saved=state(tid,material)
    assert saved[:3]==(('Montagem',1,20),8,2)
    assert len([row for row in saved[3] if row[0]=='Baixa de insumo'])==1


def test_stock_shortage_rolls_back_title_and_stage(service):
    client,auth=service;tid,material=allocated_task(service,stock=1);before=state(tid,material)
    response=client.patch(f'/tasks/{tid}',headers=auth,json={'title':'Novo título','status':1})
    assert response.status_code==409,response.text
    assert state(tid,material)==before


def test_late_automation_failure_rolls_back_consumption_and_edit(service,monkeypatch):
    client,auth=service;tid,material=allocated_task(service);before=state(tid,material)
    def fail(*args):
        raise RuntimeError('Falha de integração simulada')
    monkeypatch.setattr(main,'run_task_automations',fail)
    isolated=TestClient(main.app,raise_server_exceptions=False)
    response=isolated.patch(f'/tasks/{tid}',headers=auth,json={'title':'Novo título','status':1})
    assert response.status_code==500
    assert state(tid,material)==before


def test_password_reset_revokes_all_employee_sessions_only(service):
    client,auth=service;eid=employee(service);other=employee(service,'Outra Pessoa')
    old=worker(service,eid);other_session=worker(service,other)
    second=client.post('/auth/employee/login',json={
        'email':f'employee-{eid}@example.test','password':'worker-test-password'}).json()['token']
    response=client.post(f'/employees/{eid}/account',headers=auth,json={
        'email':f'employee-{eid}@example.test','password':'new-worker-password'})
    assert response.status_code==201,response.text
    for session in (old,{'Authorization':'Bearer '+second}):
        assert client.get('/employee/summary',headers=session).status_code==401
        assert client.post('/messages',headers=session,json={'scope':'private','body':'Tentativa antiga'}).status_code==401
    assert client.get('/employee/summary',headers=other_session).status_code==200
    assert client.get('/employees',headers=auth).status_code==200
    assert client.post('/auth/employee/login',json={
        'email':f'employee-{eid}@example.test','password':'worker-test-password'}).status_code==401
    assert client.post('/auth/employee/login',json={
        'email':f'employee-{eid}@example.test','password':'new-worker-password'}).status_code==200


@pytest.mark.parametrize('mode',['id','name','alias'])
def test_new_assignments_to_inactive_employee_are_rejected_consistently(service,mode):
    client,auth=service;eid=employee(service)
    assert client.patch(f'/employees/{eid}',headers=auth,json={'name':'Ana Torres'}).status_code==200
    assert client.delete(f'/employees/{eid}',headers=auth).status_code==200
    assignment={'assignee_employee_id':eid} if mode=='id' else {'assignee':'Ana Torres' if mode=='name' else 'Ana Lima'}
    assert client.post('/tasks',headers=auth,json={'title':'Nova',**assignment}).status_code==404
    tid=task(service)
    assert client.patch(f'/tasks/{tid}',headers=auth,json=assignment).status_code==404
    assert client.get(f'/tasks/{tid}',headers=auth).json()['assignee_employee_id'] is None


@pytest.mark.parametrize('mode',['id','name'])
def test_archived_owner_can_be_kept_on_unrelated_task_edit(service,mode):
    client,auth=service;eid=employee(service);tid=task(service,assignee_employee_id=eid)
    assert client.delete(f'/employees/{eid}',headers=auth).status_code==200
    assignment={'assignee_employee_id':eid} if mode=='id' else {'assignee':'Ana Lima'}
    response=client.patch(f'/tasks/{tid}',headers=auth,json={'title':'Novo prazo','due':'2026-12-01',**assignment})
    assert response.status_code==200,response.text
    saved=client.get(f'/tasks/{tid}',headers=auth).json()
    assert saved['title']=='Novo prazo' and saved['assignee_employee_id']==eid


@pytest.mark.parametrize('extra',[{}, {'title':'Novo título'}])
def test_explicit_null_clears_task_department(service,extra):
    client,auth=service
    department=client.post('/departments',headers=auth,json={'name':'Produção'}).json()['id']
    tid=task(service,department_id=department)
    response=client.patch(f'/tasks/{tid}',headers=auth,json={'department_id':None,**extra})
    assert response.status_code==200,response.text
    assert client.get(f'/tasks/{tid}',headers=auth).json()['department_id'] is None


def test_legacy_department_links_are_unique_active_and_synchronize_membership(service):
    client,auth=service
    ambiguous=employee(service,'Chefe ambíguo');unique=employee(service,'Chefe único');inactive=employee(service,'Chefe inativo')
    assert client.delete(f'/employees/{inactive}',headers=auth).status_code==200
    with main.db() as c:
        for name,lead in [('A','Chefe ambíguo'),('B','Chefe ambíguo'),('C','Chefe único'),('D','Chefe inativo')]:
            c.execute('INSERT INTO departments(name,lead) VALUES(?,?)',(name,lead))
        employee_identity.link_legacy_references(c)
        employee_identity.link_legacy_references(c)
        heads={row['name']:row['lead_employee_id'] for row in c.execute('SELECT name,lead_employee_id FROM departments')}
        assert heads=={'A':None,'B':None,'C':unique,'D':None}
        sector=c.execute("SELECT id FROM departments WHERE name='C'").fetchone()[0]
        assert c.execute('SELECT department_id FROM employees WHERE id=?',(unique,)).fetchone()[0]==sector
        assert c.execute('SELECT department_id FROM employees WHERE id=?',(ambiguous,)).fetchone()[0] is None
    denied=client.post('/departments',headers=auth,json={'name':'Outra chefia','lead_employee_id':unique})
    assert denied.status_code==400


def test_pin_lookup_uses_body_and_responses_are_not_cached(service):
    client,auth=service;eid=employee(service);tid=task(service,assignee_employee_id=eid,status=1)
    response=client.post('/clock/tasks',json={'employee_id':eid,'pin':'1234'})
    assert response.status_code==200 and response.json()[0]['id']==tid
    assert str(response.request.url).endswith('/clock/tasks')
    assert response.headers['cache-control']=='no-store'
    assert client.get('/clock/tasks').status_code in (404,405)
    denied=client.post('/clock/tasks',json={'employee_id':eid,'pin':'9999'})
    assert denied.status_code==401 and denied.headers['cache-control']=='no-store'


def test_explicit_external_owner_does_not_link_on_creation_edit_or_legacy_recovery(service):
    client,auth=service;eid=employee(service)
    external=task(service,assignee='Ana Lima',assignee_employee_id=None)
    internal=task(service,assignee_employee_id=eid)
    assert client.patch(f'/tasks/{internal}',headers=auth,json={
        'assignee':'Ana Lima','assignee_employee_id':None}).status_code==200
    for tid in (external,internal):
        saved=client.get(f'/tasks/{tid}',headers=auth).json()
        assert saved['assignee_employee_id'] is None and saved['assignee_external']==1
    with main.db() as c:
        employee_identity.link_legacy_references(c)
    assert client.patch(f'/employees/{eid}',headers=auth,json={'name':'Ana Torres'}).status_code==200
    for tid in (external,internal):
        saved=client.get(f'/tasks/{tid}',headers=auth).json()
        assert saved['assignee']=='Ana Lima' and saved['assignee_employee_id'] is None
    # A subsequent explicit selection of the internal person restores the link.
    assert client.patch(f'/tasks/{external}',headers=auth,json={'assignee_employee_id':eid}).status_code==200
    saved=client.get(f'/tasks/{external}',headers=auth).json()
    assert saved['assignee']=='Ana Torres' and saved['assignee_external']==0


def test_unique_prelinked_legacy_head_recovers_department_membership(service):
    client,auth=service;eid=employee(service)
    with main.db() as c:
        did=c.execute("INSERT INTO departments(name,lead,lead_employee_id) VALUES('Legado','Ana Lima',?) RETURNING id",(eid,)).fetchone()[0]
        employee_identity.link_legacy_references(c)
        assert c.execute('SELECT department_id FROM employees WHERE id=?',(eid,)).fetchone()[0]==did
