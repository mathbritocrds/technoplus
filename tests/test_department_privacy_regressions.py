"""Department identity and private HR message authorization regressions."""
import json

import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', str(tmp_path / 'departments.db'))
    monkeypatch.setattr(main, 'SUPABASE_DATABASE_URL', '')
    with main.db() as c:
        c.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(c, main.MIGRATIONS)
    client = TestClient(main.app)
    response = client.post('/auth/register', json={'email': 'owner@example.test', 'password': 'regression-password'})
    assert response.status_code == 201
    return client, {'Authorization': 'Bearer ' + response.json()['token']}


def department(service, name='Setor'):
    client, auth = service
    response = client.post('/departments', headers=auth, json={'name': name})
    assert response.status_code == 201
    return response.json()['id']


def employee(service, did=None):
    client, auth = service
    result = client.post('/employees', headers=auth, json={'name': 'Pessoa', 'salary': 1000, 'pin': '1234', 'department_id': did})
    assert result.status_code == 201
    return result.json()['id']


def test_department_with_ledger_history_cannot_be_deleted(service):
    client, auth = service
    did = department(service)
    posted = client.post('/accounting/journals', headers=auth, json={
        'booked_on': '2026-10-01', 'description': 'Despesa histórica',
        'reference': 'department-history', 'department_id': did,
        'lines': [{'account_code': '5.2.01', 'debit': '100'}, {'account_code': '2.1.01', 'credit': '100'}],
    })
    assert posted.status_code == 201
    assert client.delete(f'/departments/{did}', headers=auth).status_code == 409
    assert client.get('/departments', headers=auth).json()[0]['id'] == did
    assert department(service, 'Novo setor') > did


def test_empty_deleted_department_id_is_never_recycled(service):
    client, auth = service
    first = department(service)
    assert client.delete(f'/departments/{first}', headers=auth).status_code == 200
    assert department(service, 'Outro') > first
    assert client.delete('/departments/99999', headers=auth).status_code == 404


def test_legacy_orphaned_history_reserves_old_identifiers(service):
    client, auth = service
    # Old installations may already contain an orphaned department identifier.
    with main.db() as c:
        c.execute("INSERT INTO audit_events(at,actor,role,module,resource_id,department_id,before_json,after_json,reason) VALUES('2026-01-01','old','admin','ledger','1',100,'{}','{}','Histórico legado')")
    assert department(service) > 100


def test_employee_links_and_payroll_snapshots_preserve_department(service):
    client, auth = service
    did = department(service)
    eid = employee(service, did)
    assert client.delete(f'/departments/{did}', headers=auth).status_code == 409
    assert client.patch(f'/employees/{eid}', headers=auth, json={'department_id': None}).status_code == 200
    with main.db() as c:
        run = c.execute("INSERT INTO payroll_runs(month,closed_at,closed_by,rules_version) VALUES('2026-01','2026-02-01','owner','test') RETURNING id").fetchone()['id']
        c.execute('INSERT INTO payroll_items(run_id,employee_id,snapshot) VALUES(?,?,?)', (run, eid, json.dumps({'department_id': did})))
    assert client.delete(f'/departments/{did}', headers=auth).status_code == 409


@pytest.mark.parametrize('role', ['manager', 'operator'])
def test_delegated_messages_view_never_grants_private_hr_access(service, role):
    client, auth = service
    did = department(service)
    eid = employee(service, did)
    other = employee(service)
    account = {'email': role + '@example.test', 'password': 'regression-password', 'role': role}
    if role == 'manager':
        account.update(department_id=did, employee_id=eid)
    assert client.post('/auth/register', headers=auth, json=account).status_code == 201
    token = client.post('/auth/login', json={'email': account['email'], 'password': account['password']}).json()['token']
    viewer = {'Authorization': 'Bearer ' + token}
    assert client.put('/admin/permissions', headers=auth, json={'permissions': [
        {'role': role, 'module': 'messages', 'permission': 'view', 'allowed': True},
    ]}).status_code == 200
    assert client.post('/messages', headers=auth, json={'scope': 'team', 'body': 'Aviso geral'}).status_code == 201
    assert client.post('/messages', headers=auth, json={'scope': 'private', 'employee_id': other, 'body': 'Dados médicos privados'}).status_code == 201
    general = client.get('/messages', headers=viewer)
    assert general.status_code == 200
    assert [item['body'] for item in general.json()] == ['Aviso geral']
    # A module-level permission never changes the private-conversation policy.
    assert client.get(f'/messages?employee_id={other}', headers=viewer).status_code == 403
    assert client.get(f'/messages?employee_id={eid}', headers=viewer).status_code == 403
    assert client.post('/messages', headers=viewer, json={'scope': 'private', 'employee_id': other, 'body': 'Não autorizado'}).status_code == 403
    assert client.get(f'/messages?employee_id={other}', headers=auth).status_code == 200


def test_payroll_complement_alone_preserves_department(service):
    client, auth = service
    did = department(service)
    with main.db() as c:
        c.execute("INSERT INTO payroll_adjustments(month,reference,reason,booked_on,created_at,created_by,current_json,delta_json) VALUES('2026-01','department-complement','Correção histórica','2026-02-01','2026-02-01','owner',?,?)", (json.dumps([{'department_id': did}]), '[]'))
    assert client.delete(f'/departments/{did}', headers=auth).status_code == 409
