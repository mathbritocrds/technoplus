"""Payroll boundaries, vacation controls and request-scoped batch regressions."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import business, main, payroll as hr


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', str(tmp_path / 'hr-process.db'))
    monkeypatch.setattr(main, 'SUPABASE_DATABASE_URL', '')
    with main.db() as connection:
        connection.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(connection, main.MIGRATIONS)
    client = TestClient(main.app)
    result = client.post('/auth/register', json={'email': 'hr-process@example.test', 'password': 'process-test-password'})
    assert result.status_code == 201
    return client, {'Authorization': 'Bearer ' + result.json()['token']}


def add_employee(service, hired='2024-01-01', name='Ana'):
    client, headers = service
    result = client.post('/employees', headers=headers, json={
        'name': name, 'salary': 3000, 'pin': '1234', 'hired_on': hired,
    })
    assert result.status_code == 201
    return result.json()['id']


def test_close_rejects_empty_and_pending_time_records(service):
    client, headers = service
    assert client.post('/payroll/close', headers=headers, json={'month': '2026-02'}).status_code == 409
    eid = add_employee(service)
    with main.db() as c:
        c.execute("INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,'entrada','2026-02-02T12:00:00+00:00',1)", (eid,))
    result = client.post('/payroll/close', headers=headers, json={'month': '2026-02'})
    assert result.status_code == 409
    assert 'ponto pendentes' in result.json()['detail']
    with main.db() as c:
        assert c.execute('SELECT COUNT(*) FROM payroll_runs').fetchone()[0] == 0
        assert c.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 0


def test_vacation_rights_stop_at_termination_and_gozo_cannot_follow_it(service):
    client, headers = service
    eid = add_employee(service)
    profile = {'hired_on': '2024-01-01', 'terminated_on': '2024-06-01'}
    assert client.put(f'/employees/{eid}/payroll-profile', headers=headers, json=profile).status_code == 200
    result = client.post(f'/employees/{eid}/vacations/quote', headers=headers, json={
        'acquisition_start': '2025-01-01', 'starts_on': '2026-02-02', 'days': 30,
    })
    assert result.status_code == 409
    balance = hr.entitlement({**hr.PROFILE_DEFAULTS, **profile, 'remuneration': 3000}, date(2026, 2, 2), [])
    assert balance['vacation_cycles'] == []
    assert balance['vacation_months'] == 5


def test_vacation_consent_fragmentation_and_calendar(service):
    client, headers = service
    eid = add_employee(service)
    endpoint = f'/employees/{eid}/vacations'
    payload = {'acquisition_start': '2024-01-01', 'starts_on': '2026-02-02', 'days': 14}
    assert client.post(endpoint + '/quote', headers=headers, json=payload).status_code == 200
    assert client.post(endpoint, headers=headers, json=payload).status_code == 409
    assert client.post(endpoint, headers=headers, json={**payload, 'days': 1, 'consent': True}).status_code == 409
    assert client.post(endpoint, headers=headers, json={**payload, 'starts_on': '2026-02-06', 'consent': True}).status_code == 409
    assert client.post(endpoint, headers=headers, json={**payload, 'consent': True}).status_code == 201
    for start in ('2026-03-02', '2026-04-06'):
        assert client.post(endpoint, headers=headers, json={**payload, 'starts_on': start, 'days': 5, 'consent': True}).status_code == 201
    assert client.post(endpoint, headers=headers, json={**payload, 'starts_on': '2026-05-04', 'days': 6, 'consent': True}).status_code == 409
    with main.db() as c:
        event = c.execute("SELECT after_json FROM audit_events WHERE module='vacation' ORDER BY id LIMIT 1").fetchone()
        assert json.loads(event['after_json'])['consent'] is True


def test_vacation_holiday_and_reduced_entitlement(service):
    client, headers = service
    eid = add_employee(service)
    payload = {'acquisition_start': '2024-01-01', 'starts_on': '2026-02-02', 'days': 12, 'consent': True}
    client.put(f'/employees/{eid}/payroll-profile', headers=headers, json={'hired_on': '2024-01-01', 'vacation_days': 12})
    with main.db() as c:
        c.execute("INSERT INTO settings(k,v) VALUES('vacation_holidays','[\"2026-02-04\"]')")
    assert client.post(f'/employees/{eid}/vacations', headers=headers, json=payload).status_code == 409
    with main.db() as c:
        c.execute("DELETE FROM settings WHERE k='vacation_holidays'")
    assert client.post(f'/employees/{eid}/vacations', headers=headers, json=payload).status_code == 201


def test_payroll_query_count_is_independent_of_staff_count_and_scope(service):
    add_employee(service)
    with main.db() as c:
        statements = []
        c.set_trace_callback(lambda statement: statements.append(statement) if statement.lstrip().upper().startswith('SELECT') else None)
        business.payroll_data(main.services, '2026-02', c)
        one_count = len(statements)
        c.set_trace_callback(None)
        for i in range(29):
            c.execute("INSERT INTO employees(name,salary,active) VALUES(?,3000,1)", (f'Pessoa {i}',))
        statements.clear()
        c.set_trace_callback(lambda statement: statements.append(statement) if statement.lstrip().upper().startswith('SELECT') else None)
        data = business.payroll_data(main.services, '2026-02', c)
        assert len(data['employees']) == 30
        assert len(statements) == one_count
        first = data['employees'][0]['id']
        scoped = business.payroll_data(main.services, '2026-02', c, employee_id=first)
        assert [row['id'] for row in scoped['employees']] == [first]


def test_overtime_salary_divisor_and_multiplier_are_configurable():
    employee = {'id': 1, 'name': 'Ana', 'role': '', 'department_id': None, 'salary': 3000, 'benefits': 0}
    result = hr.calculate(employee, {'hired_on': '2024-01-01'}, '2026-02', overtime_hours=2,
                          salary_hour_divisor=200, overtime_multiplier=2)
    assert result['overtime_pay'] == 60
