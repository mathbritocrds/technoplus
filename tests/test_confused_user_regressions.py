"""Accepted configuration must remain usable and reject visually blank policies."""
import json

import pytest
from fastapi.testclient import TestClient

from app import main, payroll as hr
from app.tax_registry import approve_table, get_tax_rules


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', str(tmp_path/'confused.db'))
    monkeypatch.setattr(main, 'SUPABASE_DATABASE_URL', '')
    with main.db() as c:
        c.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(c, main.MIGRATIONS)
    client = TestClient(main.app)
    registration = client.post('/auth/register', json={
        'email':'confused@example.test', 'password':'confused-test-password',
    })
    assert registration.status_code == 201
    return client, {'Authorization':'Bearer '+registration.json()['token']}


def fiscal_table():
    # Synthetic future approval exercises configuration, not future tax law.
    table = json.loads(json.dumps(hr.tax_rules('2026-01')))
    table.pop('inss_offsets', None)
    table.update(version='SYNTHETIC-CONFUSED-2027',
                 irrf_reduction_full_limit=5000, irrf_reduction_full_amount=312.89,
                 irrf_reduction_taper_limit=7350, irrf_reduction_taper_offset=978.62,
                 irrf_reduction_taper_rate=.133145)
    return table


def policy():
    return dict(vacation_rest_weekdays=[6],vacation_holidays=[],
                external_payroll_provider=' Escritório responsável ',
                reviewed_regime=' Regime revisado ',reviewed_agreement=' Convenção revisada ',
                reason=' Revisão confirmada pelo responsável ')


def test_approval_without_display_offsets_returns_usable_future_rules(service):
    client, auth = service
    table = fiscal_table()
    request = {'year':2027,'source':'https://example.test/synthetic-table','table':table,
               'reason':'Tabela sintética para verificar contrato de configuração'}
    result = client.post('/compliance/tax-rules', headers=auth, json=request)
    assert result.status_code == 200, result.text
    assert result.json()['table']['inss_offsets'] == [0,24.32,111.4,198.49]
    rules = client.get('/payroll/rules?month=2027-01', headers=auth)
    assert rules.status_code == 200
    assert rules.json()['inss_offsets'] == [0,24.32,111.4,198.49]
    assert client.get('/payroll?month=2027-01', headers=auth).status_code == 200
    assert client.get('/payroll/annual-cost?year=2027', headers=auth).status_code == 200
    assert 'inss_offsets' not in table


def test_legacy_approval_without_metadata_remains_readable_and_idempotent(service):
    table = fiscal_table()
    record = {'year':2027,'table':table,'source':'https://example.test/synthetic-table',
              'approved_by':'legacy','approved_at':'2026-01-01'}
    with main.db() as c:
        for key in ['tax_rules:2027', 'tax_rules:2027:'+table['version']]:
            c.execute('INSERT INTO settings(k,v) VALUES(?,?)', (key,json.dumps(record)))
        assert get_tax_rules(c,'2027-01')['inss_offsets'] == [0,24.32,111.4,198.49]
        approve_table(c,2027,table,record['source'],'new-reviewer','2026-11-01')
        stored = json.loads(c.execute('SELECT v FROM settings WHERE k=?',
                                     ('tax_rules:2027:'+table['version'],)).fetchone()['v'])
        assert stored == record  # Derived display metadata does not rewrite history.


def test_offsets_are_derived_from_bands_not_untrusted_display_input(service):
    table = fiscal_table()
    table['inss_offsets'] = ['bad',None,9999]
    with main.db() as c:
        record = approve_table(c,2027,table,'https://example.test/synthetic-table','admin','now')
        assert record['table']['inss_offsets'] == [0,24.32,111.4,198.49]


@pytest.mark.parametrize('field', ['external_payroll_provider','reviewed_regime','reviewed_agreement','reason'])
def test_visually_blank_policy_is_rejected_before_configuration(service, field):
    client, auth = service
    result = client.put('/compliance/policy',headers=auth,json={**policy(),field:' '*12})
    assert result.status_code == 422
    assert client.get('/compliance/policy',headers=auth).json() == {'configured':False}


@pytest.mark.parametrize('days', [[],[0,0],[''],['0'],[True],[1.5],[7],[-1]])
def test_policy_rejects_malformed_or_duplicate_rest_days(service, days):
    client, auth = service
    result = client.put('/compliance/policy',headers=auth,json={**policy(),'vacation_rest_weekdays':days})
    assert result.status_code == 422
    assert client.get('/compliance/policy',headers=auth).json() == {'configured':False}


def test_valid_policy_is_trimmed_and_invalid_updates_preserve_it(service):
    client, auth = service
    result = client.put('/compliance/policy',headers=auth,json=policy())
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved['external_payroll_provider'] == 'Escritório responsável'
    assert saved['reviewed_regime'] == 'Regime revisado'
    assert saved['reviewed_agreement'] == 'Convenção revisada'
    assert saved['reason'] == 'Revisão confirmada pelo responsável'
    invalid = client.put('/compliance/policy',headers=auth,json={**policy(),'reviewed_regime':'   '})
    assert invalid.status_code == 422
    assert client.get('/compliance/policy',headers=auth).json() == saved


def test_get_policy_flags_legacy_blank_settings_without_rewriting_history(service):
    client, auth = service
    saved = {**policy(), 'external_payroll_provider':'   ', 'configured':True,
             'reviewed_by':'legacy-admin', 'reviewed_at':'2026-10-01'}
    original = json.dumps(saved)
    with main.db() as c:
        c.execute("INSERT INTO settings(k,v) VALUES('compliance_policy',?)", (original,))
    response = client.get('/compliance/policy', headers=auth)
    assert response.status_code == 200
    displayed = response.json()
    assert displayed['configured'] is False and displayed['needs_review'] is True
    assert 'revisão' in displayed['message']
    assert 'external_payroll_provider' not in displayed
    with main.db() as c:
        assert c.execute("SELECT v FROM settings WHERE k='compliance_policy'").fetchone()['v'] == original


def test_checklist_flags_legacy_duplicate_days_without_rewriting_history(service):
    client, auth = service
    saved = {**policy(), 'vacation_rest_weekdays':[0,0], 'configured':True,
             'reviewed_by':'legacy-admin', 'reviewed_at':'2026-10-01'}
    original = json.dumps(saved)
    with main.db() as c:
        c.execute("INSERT INTO settings(k,v) VALUES('compliance_policy',?)", (original,))
    response = client.get('/compliance/checklist?month=2026-10', headers=auth)
    assert response.status_code == 200
    displayed = response.json()['policy']
    assert displayed['configured'] is False and displayed['needs_review'] is True
    assert 'vacation_rest_weekdays' not in displayed
    with main.db() as c:
        assert c.execute("SELECT v FROM settings WHERE k='compliance_policy'").fetchone()['v'] == original
