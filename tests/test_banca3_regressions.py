"""Regressions for the third independent review board."""
from decimal import Decimal
from unittest.mock import patch

import pytest

from app import main, payroll, timekeeping
from tests.test_employee_rename import service, employee


def clock(eid, days):
    with main.db() as db:
        for day in days:
            for kind, hour in [('entrada', 9), ('saida', 17)]:
                db.execute('INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,?,?,1)',
                           (eid, kind, f'2026-02-{day:02d}T{hour:02d}:00:00-03:00'))


def test_pre_hire_hours_do_not_consume_weekly_allowance(service):
    client, auth = service
    eid = employee(service, hired_on='2026-02-11')
    assert client.put(f'/employees/{eid}/payroll-profile', headers=auth, json={
        'hired_on': '2026-02-11', 'pay_basis': 'hourly', 'hourly_rate': 20}).status_code == 200
    clock(eid, range(9, 15))
    result = client.get('/payroll?month=2026-02', headers=auth).json()['employees'][0]
    assert (result['worked_hours'], result['overtime_hours'], result['gross']) == (32, 0, 720)
    with main.db() as db:
        assert db.execute('SELECT COUNT(*) FROM time_entries').fetchone()[0] == 12


@pytest.mark.parametrize('hours', [0, 160])
def test_hourly_full_vacation_provision(hours):
    result = payroll.calculate({'id': 1, 'name': 'Horista', 'role': '', 'department_id': None, 'salary': 3000, 'benefits': 0},
        {'hired_on': '2026-01-01', 'pay_basis': 'hourly', 'hourly_rate': 20,
         'reference_monthly_hours': 160}, '2026-02', worked_hours=hours)
    assert result['vacation_salary_offset'] == result['vacation_charge_offset'] == 0
    expected = sum(Decimal(str(result[key])) for key in
                   ['company_cost', 'thirteenth_provision', 'vacation_provision', 'provision_charges'])
    assert Decimal(str(result['accrual_cost'])) == expected
    if not hours:
        assert result['accrual_cost'] == 796.45


def test_annual_pairs_once_and_does_not_load_completed_old_history(service):
    client, auth = service
    eid = employee(service)
    clock(eid, [2, 3])
    with main.db() as db:
        for kind, hour in [('entrada', 9), ('saida', 17)]:
            db.execute('INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,?,?,1)',
                       (eid, kind, f'2024-01-02T{hour:02d}:00:00-03:00'))
    with patch('app.timekeeping.summarize', wraps=timekeeping.summarize) as summarize:
        response = client.get('/payroll/annual-cost?year=2026', headers=auth)
    assert response.status_code == 200, response.text
    assert summarize.call_count == 1
    rows = summarize.call_args.args[0]
    assert len(rows) == 4
    assert all(row['at'].startswith('2026') for row in rows)


def test_month_end_shift_uses_next_exit_without_losing_hours(service):
    from datetime import timezone, timedelta
    eid = employee(service)
    with main.db() as db:
        for kind, stamp in [('entrada', '2026-01-31T22:00:00-03:00'),
                            ('saida', '2026-02-01T06:00:00-03:00')]:
            db.execute('INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,?,?,1)',
                       (eid, kind, stamp))
        result = timekeeping.payroll_months(db, ['2026-01'], {}, timezone(timedelta(hours=-3)))
    assert result['2026-01'][eid]['total'] == 2
    assert result['2026-01'][eid]['open'] is None


def test_old_unresolved_entry_still_blocks_closing(service):
    client, auth = service
    eid = employee(service)
    with main.db() as db:
        db.execute('INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,?,?,1)',
                   (eid, 'entrada', '2025-10-01T09:00:00-03:00'))
    response = client.post('/payroll/close', headers=auth, json={'month': '2026-02'})
    assert response.status_code == 409
    assert 'ponto pendentes' in response.text


def test_hourly_closing_freezes_full_provision(service):
    client, auth = service
    eid = employee(service, hired_on='2026-01-01')
    assert client.put(f'/employees/{eid}/payroll-profile', headers=auth, json={
        'hired_on': '2026-01-01', 'pay_basis': 'hourly', 'hourly_rate': 20,
        'reference_monthly_hours': 160}).status_code == 200
    response = client.post('/payroll/close', headers=auth, json={'month': '2026-02'})
    assert response.status_code == 200, response.text
    assert client.put(f'/employees/{eid}/payroll-profile', headers=auth,
                      json={'hourly_rate': 40}).status_code == 200
    saved = client.get('/payroll?month=2026-02', headers=auth).json()['employees'][0]
    assert saved['accrual_cost'] == 796.45
    assert saved['vacation_salary_offset'] == saved['vacation_charge_offset'] == 0
