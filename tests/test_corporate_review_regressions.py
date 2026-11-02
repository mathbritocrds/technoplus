"""Independent review regressions for month boundaries and historical allocation."""
from datetime import datetime, timezone

from app import main
from tests.test_corporate_controls import service


def test_payroll_complement_keeps_original_department_obligations(service):
    client, auth = service
    old = client.post('/departments', headers=auth, json={'name': 'Original'}).json()['id']
    new = client.post('/departments', headers=auth, json={'name': 'Novo'}).json()['id']
    eid = client.post('/employees', headers=auth, json={
        'name': 'Ana', 'salary': 3000, 'pin': '1234', 'hired_on': '2025-01-01', 'department_id': old,
    }).json()['id']
    assert client.post('/payroll/close', headers=auth, json={'month': '2026-10'}).status_code == 200
    generation = {'month': '2026-10', 'due': '2026-11-20', 'reason': 'Guias conferidas pelo responsável fiscal'}
    assert client.post('/compliance/obligations/generate', headers=auth, json=generation).status_code == 200
    assert client.patch(f'/employees/{eid}', headers=auth, json={'salary': 3300, 'department_id': new}).status_code == 200
    adjustment = client.post('/payroll/adjustments', headers=auth, json={
        'month': '2026-10', 'reference': 'transferred-salary-review', 'booked_on': '2026-11-02',
        'reason': 'Reajuste retroativo após transferência de setor',
    })
    assert adjustment.status_code == 200, adjustment.text
    assert {delta['department_id'] for delta in adjustment.json()['deltas']} == {old}
    assert client.post('/compliance/obligations/generate', headers=auth, json=generation).status_code == 200
    obligations = client.get('/compliance/obligations?month=2026-10', headers=auth).json()['items']
    assert {item['department_id'] for item in obligations} == {old}
    assert all(item['generated'] == item['calculated'] for item in obligations)
    with main.db() as c:
        assert c.execute("SELECT COUNT(*) FROM transactions WHERE source_key LIKE 'payroll:obligation:%' AND department_id=?", (new,)).fetchone()[0] == 0


def local_october_payment(client, auth, monkeypatch):
    # The ledger recognizes the payment on October 31 in the company's timezone.
    monkeypatch.setattr(main, 'utcnow', lambda: datetime(2026, 11, 1, 1, tzinfo=timezone.utc))
    created = client.post('/finance', headers=auth, json={
        'kind': 'pagar', 'description': 'Pagamento na virada UTC', 'amount': 100, 'due': '2026-10-31',
    })
    assert created.status_code == 201
    assert client.patch(f"/finance/{created.json()['id']}/paid", headers=auth, json={'paid': True}).status_code == 200
    with main.db() as c:
        return c.execute('SELECT id FROM payment_history').fetchone()['id']


def test_accounting_close_requires_local_month_payment_reconciliation(service, monkeypatch):
    client, auth = service
    local_october_payment(client, auth, monkeypatch)
    response = client.post('/accounting/periods/close', headers=auth, json={
        'month': '2026-10', 'reason': 'Conferência da competência local',
    })
    assert response.status_code == 409, response.text
    assert 'Concilie' in response.json()['detail']


def test_bank_matching_uses_local_payment_date_for_tolerance(service, monkeypatch):
    client, auth = service
    payment_id = local_october_payment(client, auth, monkeypatch)
    monkeypatch.setattr(main, 'utcnow', lambda: datetime(2026, 11, 12, 12, tzinfo=timezone.utc))
    response = client.post('/accounting/bank-entries/import', headers=auth, json={
        'account': 'Conta principal',
        'content': 'reference;date;amount;description\nmonth-boundary;2026-11-11;-100.00;Pagamento\n',
    })
    assert response.status_code == 200
    entry = client.get('/accounting/bank-entries?month=2026-11', headers=auth).json()[0]
    matched = client.post(f"/accounting/bank-entries/{entry['id']}/match", headers=auth, json={
        'payment_id': payment_id, 'reason': 'Conferência das datas locais do banco',
    })
    assert matched.status_code == 409, matched.text
    assert 'dez dias' in matched.json()['detail']


def test_database_period_guard_rejects_posting_draft_into_closed_month(service):
    import pytest
    client, auth = service
    with main.db() as c:
        jid = c.execute("INSERT INTO ledger_journals(booked_on,description,source_key,payload_hash,created_at,created_by) VALUES('2026-11-01','Rascunho em período aberto','draft-period-review','x','now','owner') RETURNING id").fetchone()['id']
        c.execute("INSERT INTO ledger_lines(journal_id,account_code,debit_cents,credit_cents) VALUES(?,'1.1.01',100,0)", (jid,))
        c.execute("INSERT INTO ledger_lines(journal_id,account_code,debit_cents,credit_cents) VALUES(?,'3.1.01',0,100)", (jid,))
    assert client.post('/accounting/periods/close', headers=auth, json={
        'month': '2026-10', 'reason': 'Conferência mensal concluída',
    }).status_code == 200
    with main.db() as c:
        with pytest.raises(Exception, match='encerrada'):
            c.execute("UPDATE ledger_journals SET booked_on='2026-10-01',status='posted' WHERE id=?", (jid,))
    with main.db() as c:
        row = c.execute('SELECT booked_on,status FROM ledger_journals WHERE id=?', (jid,)).fetchone()
        assert (row['booked_on'], row['status']) == ('2026-11-01', 'draft')
