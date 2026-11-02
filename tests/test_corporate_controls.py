"""Cross-module administrative controls with isolated persistence."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import main
from app import payroll as hr


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(main,'DB',str(tmp_path/'corporate.db'))
    monkeypatch.setattr(main,'SUPABASE_DATABASE_URL','')
    with main.db() as c:
        c.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(c,main.MIGRATIONS)
    client=TestClient(main.app)
    response=client.post('/auth/register',json={'email':'controls@test.example','password':'secure-controls-password'})
    assert response.status_code==201
    return client,{'Authorization':'Bearer '+response.json()['token']}


def payroll(service):
    client,auth=service
    eid=client.post('/employees',headers=auth,json={'name':'Ana','salary':3000,'pin':'1234','hired_on':'2025-01-01'}).json()['id']
    response=client.post('/payroll/close',headers=auth,json={'month':'2026-10'})
    assert response.status_code==200,response.text
    return eid


def journal(reference='journal-ref-1',booked_on='2026-10-20'):
    return {'booked_on':booked_on,'description':'Capital inicial','reference':reference,
            'lines':[{'account_code':'1.1.01','debit':'100.00'},{'account_code':'3.1.01','credit':'100.00'}]}


def test_period_close_blocks_manual_automatic_and_direct_posting_with_audited_reopen(service):
    client,auth=service
    assert client.post('/accounting/journals',headers=auth,json=journal()).status_code==201
    payload={'month':'2026-10','reason':'Conferência mensal concluída'}
    assert client.post('/accounting/periods/close',headers=auth,json=payload).status_code==200
    # An exact retry remains idempotent even after period close.
    assert client.post('/accounting/journals',headers=auth,json=journal()).status_code==201
    assert client.post('/accounting/journals',headers=auth,json=journal('journal-ref-2')).status_code==409
    assert client.post('/finance',headers=auth,json={'kind':'pagar','description':'Despesa retroativa','amount':20,'due':'2026-10-25'}).status_code==409
    with main.db() as c:
        assert c.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]==0
        with pytest.raises(Exception,match='encerrada'):
            c.execute("INSERT INTO ledger_journals(booked_on,description,source_key,payload_hash,created_at,created_by) VALUES('2026-10-01','Bypass','bypass','x','now','admin')")
    assert client.post('/accounting/periods/reopen',headers=auth,json=payload).status_code==200
    assert client.post('/accounting/journals',headers=auth,json=journal('journal-ref-2')).status_code==201
    with main.db() as c:
        assert c.execute("SELECT COUNT(*) FROM audit_events WHERE module='accounting_period'").fetchone()[0]==2


def test_complement_is_atomic_idempotent_preserves_original_and_updates_dre(service):
    client,auth=service;eid=payroll(service)
    with main.db() as c:
        original=c.execute('SELECT snapshot FROM payroll_items').fetchone()[0]
    assert client.patch(f'/employees/{eid}',headers=auth,json={'salary':3300}).status_code==200
    body={'month':'2026-10','reference':'salary-correction-1','booked_on':'2026-11-02','reason':'Reajuste salarial retroativo aprovado'}
    response=client.post('/payroll/adjustments',headers=auth,json=body)
    assert response.status_code==200,response.text
    assert response.json()['deltas'][0]['net']>0
    assert client.post('/payroll/adjustments',headers=auth,json=body).json()['already_created']
    assert client.post('/payroll/adjustments',headers=auth,json={**body,'reference':'salary-correction-2'}).status_code==409
    with main.db() as c:
        assert c.execute('SELECT snapshot FROM payroll_items').fetchone()[0]==original
        assert c.execute('SELECT COUNT(*) FROM payroll_adjustments').fetchone()[0]==1
        assert c.execute("SELECT COUNT(*) FROM transactions WHERE source_key LIKE 'payroll:adjustment:%'").fetchone()[0]==1
        with pytest.raises(Exception,match='imutável'):
            c.execute("UPDATE payroll_adjustments SET reason='other'")
    effective=client.get('/payroll?month=2026-10',headers=auth).json()
    assert effective['employees'][0]['base_salary']==3300
    report=client.get('/finance/dre?start=2026-10&end=2026-10',headers=auth)
    assert report.status_code==200,report.text
    assert report.json()['personnel']==effective['total_accrual_cost']
    assert client.get('/accounting/reports?start=2026-10-01&end=2026-11-30',headers=auth).json()['trial']['balanced']


def test_obligation_generation_does_not_double_expense_or_duplicate_payables(service):
    client,auth=service;payroll(service)
    payload={'month':'2026-10','due':'2026-11-20','reason':'Guias conferidas pelo responsável fiscal'}
    response=client.post('/compliance/obligations/generate',headers=auth,json=payload)
    assert response.status_code==200,response.text
    assert len(response.json()['created'])>=3
    assert client.post('/compliance/obligations/generate',headers=auth,json=payload).json()['created']==[]
    status=client.get('/compliance/obligations?month=2026-10',headers=auth).json()
    assert all(row['calculated']==row['generated'] for row in status['items'])
    with main.db() as c:
        assert c.execute('SELECT COUNT(*) FROM ledger_journals').fetchone()[0]==1


def test_bank_reconciliation_idempotence_amount_direction_and_period_close(service):
    client,auth=service
    now=date.today().isoformat();month=now[:7]
    tid=client.post('/finance',headers=auth,json={'kind':'pagar','description':'Conta bancária','amount':100,'due':now}).json()['id']
    response=client.patch(f'/finance/{tid}/paid',headers=auth,json={'paid':True})
    assert response.status_code==200,response.text
    payment=client.get('/finance/payments?month='+month,headers=auth).json()[0]
    payload={'account':'Conta principal','content':f'reference;date;amount;description\nref-1;{now};-100.00;Pagamento\n'}
    assert client.post('/accounting/bank-entries/import',headers=auth,json=payload).json()['inserted']==1
    assert client.post('/accounting/bank-entries/import',headers=auth,json=payload).json()['inserted']==0
    assert client.post('/accounting/bank-entries/import',headers=auth,json={**payload,'content':payload['content'].replace('-100.00','-101.00')}).status_code==409
    close={'month':month,'reason':'Conferência mensal concluída'}
    assert client.post('/accounting/periods/close',headers=auth,json=close).status_code==409
    entry=client.get('/accounting/bank-entries?month='+month,headers=auth).json()[0]
    match={'payment_id':payment['id'],'reason':'Conferido contra extrato da conta principal'}
    assert client.post(f"/accounting/bank-entries/{entry['id']}/match",headers=auth,json=match).status_code==200
    assert client.post(f"/accounting/bank-entries/{entry['id']}/match",headers=auth,json=match).json()['already_matched']
    assert client.post('/accounting/periods/close',headers=auth,json=close).status_code==200


def test_external_evidence_is_append_only_and_not_transmission(service):
    client,auth=service
    payload={'month':'2026-10','kind':'esocial','reference':'esocial-protocol-123','evidence':'Arquivo assinado pelo escritório externo','reason':'Conferência do protocolo informado'}
    first=client.post('/compliance/records',headers=auth,json=payload)
    assert first.status_code==200,first.text
    assert client.post('/compliance/records',headers=auth,json=payload).json()['id']==first.json()['id']
    assert client.post('/compliance/records',headers=auth,json={**payload,'evidence':'Documento diferente'}).status_code==409
    result=client.get('/compliance/checklist?month=2026-10',headers=auth).json()
    assert len(result['records'])==1 and 'Não constituem transmissão' in result['notice']


def test_tax_year_fails_closed_until_reviewed_version_is_approved(service):
    client,auth=service
    assert client.get('/payroll?month=2027-01',headers=auth).status_code==422
    # Test-only synthetic table. No production table or official rate is invented.
    table=json.loads(json.dumps(hr.tax_rules('2026-01')))
    table.update(version='SYNTHETIC-TEST-2027',irrf_reduction_full_limit=5000,irrf_reduction_full_amount=312.89,
                 irrf_reduction_taper_limit=7350,irrf_reduction_taper_offset=978.62,irrf_reduction_taper_rate=.133145)
    payload={'year':2027,'source':'https://official.example.test/table','table':table,'reason':'Tabela sintética apenas para teste de governança'}
    assert client.post('/compliance/tax-rules',json=payload).status_code==401
    assert client.post('/compliance/tax-rules',headers=auth,json=payload).status_code==200
    assert client.get('/payroll?month=2027-01',headers=auth).status_code==200
    changed=json.loads(json.dumps(payload));changed['table']['inss_max']=1
    assert client.post('/compliance/tax-rules',headers=auth,json=changed).status_code==422
    assert client.post('/compliance/tax-rules',headers=auth,json={**payload,'source':'http://untrusted.test/table'}).status_code==422


def test_accounting_close_requires_payroll_of_eligible_employees(service):
    client,auth=service
    client.post('/employees',headers=auth,json={'name':'Ana','salary':3000,'pin':'1234','hired_on':'2025-01-01'})
    payload={'month':'2026-10','reason':'Conferência mensal concluída'}
    response=client.post('/accounting/periods/close',headers=auth,json=payload)
    assert response.status_code==409 and 'Feche a folha' in response.json()['detail']
    assert client.post('/payroll/close',headers=auth,json={'month':'2026-10'}).status_code==200
    assert client.post('/accounting/periods/close',headers=auth,json=payload).status_code==200
