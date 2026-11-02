"""Regression checks for partial edits and explicit field removal."""
import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', str(tmp_path / 'edits.db'))
    monkeypatch.setattr(main, 'SUPABASE_DATABASE_URL', '')
    with main.db() as connection:
        connection.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(connection, main.MIGRATIONS)
    client = TestClient(main.app)
    response = client.post('/auth/register', json={'email': 'edits@example.test', 'password': 'regression-password'})
    assert response.status_code == 201
    return client, {'Authorization': 'Bearer ' + response.json()['token']}


def employee(service, **extra):
    client, auth = service
    response = client.post('/employees', headers=auth, json={
        'name': 'Ana', 'salary': 1000, 'pin': '1234', **extra,
    })
    assert response.status_code == 201
    return response.json()['id']


def test_department_null_removes_link_but_omission_preserves_it(service):
    client, auth = service
    department = client.post('/departments', headers=auth, json={'name': 'Equipe'}).json()['id']
    eid = employee(service, department_id=department)
    assert client.patch(f'/employees/{eid}', headers=auth, json={'role': 'Analista'}).status_code == 200
    assert client.get('/employees', headers=auth).json()[0]['department_id'] == department
    assert client.patch(f'/employees/{eid}', headers=auth, json={'department_id': None}).status_code == 200
    assert client.get('/employees', headers=auth).json()[0]['department_id'] is None


@pytest.mark.parametrize('name', ['', '   ', None])
def test_employee_edit_rejects_blank_name(service, name):
    client, auth = service
    eid = employee(service)
    assert client.patch(f'/employees/{eid}', headers=auth, json={'name': name}).status_code == 422
    assert client.get('/employees', headers=auth).json()[0]['name'] == 'Ana'


def test_employee_edit_checks_department_exists(service):
    client, auth = service
    eid = employee(service)
    assert client.patch(f'/employees/{eid}', headers=auth, json={'department_id': 9999}).status_code == 404


def test_partial_cost_changes_do_not_overwrite_other_fields(service):
    client, auth = service
    pid = client.post('/products', headers=auth, json={'name': 'Produto', 'material': 10, 'price': 30}).json()['id']
    assert client.patch(f'/products/{pid}', headers=auth, json={'material': 20}).status_code == 200
    assert client.patch(f'/products/{pid}', headers=auth, json={'price': 50}).status_code == 200
    product = client.get('/products', headers=auth).json()[0]
    assert (product['material'], product['price'], product['profit']) == (20, 50, 30)
    assert client.patch(f'/products/{pid}', headers=auth, json={'price': ''}).status_code == 422
    assert client.patch(f'/products/{pid}', headers=auth, json={'price': -1}).status_code == 422
    assert client.patch('/products/9999', headers=auth, json={'price': 5}).status_code == 404


def test_clearing_department_preserves_leadership_guard(service):
    client, auth = service
    eid = employee(service)
    department = client.post('/departments', headers=auth, json={'name': 'Equipe', 'lead_employee_id': eid})
    assert department.status_code == 201
    response = client.patch(f'/employees/{eid}', headers=auth, json={'department_id': None})
    assert response.status_code == 409
    assert client.get('/employees', headers=auth).json()[0]['department_id'] == department.json()['id']
