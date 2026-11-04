"""The screenshot's accounting DRE uses the supplied model over real ledger values."""
import csv,io
import pytest
from app.accounting import inter_statement,statement
from tests.test_accounting import service,journal,pair


def test_inter_adapter_preserves_special_categories_and_exact_result():
    totals={'revenue':1000000,'deductions':-50000,'cost':-150000,'operating':-200000,
        'other_operating':20000,'investment':50000,'financing':-30000,'income_tax':-40000,'discontinued':10000}
    rows={row['key']:row for row in inter_statement(totals)}
    old={row['key']:row for row in statement(totals)}
    assert rows['net_profit']['amount_cents']==old['net_profit']['amount_cents']==610000
    assert rows['financial_result']['amount_cents']==20000
    assert rows['other_operating']['amount_cents']==20000
    assert rows['income_tax']['amount_cents']==40000
    assert rows['discontinued']['amount_cents']==10000
    assert rows['tax']['amount_cents']==50000


def test_empty_inter_model_has_workbook_ten_rows_and_no_divide_by_zero():
    rows=inter_statement({})
    assert len(rows)==10 and all(row['amount_cents']==0 and row['revenue_pct'] is None for row in rows)


def test_accounting_api_and_inter_csv_reconcile_with_balance(service):
    client,auth=service
    assert journal(client,auth,'Receita-print',pair('1.1.01','4.1.01','1000')).status_code==201
    assert journal(client,auth,'Despesa-print',pair('5.3.01','1.1.01','200')).status_code==201
    params='start=2026-10-01&end=2026-10-31'
    data=client.get('/accounting/reports?'+params,headers=auth).json()
    assert data['balance']['balanced'] and data['trial']['balanced']
    assert data['inter_dre'][-1]['amount_cents']==data['dre'][-1]['amount_cents']==80000
    response=client.get('/accounting/export.csv?'+params+'&kind=dre_inter',headers=auth)
    assert response.status_code==200
    rows=list(csv.reader(io.StringIO(response.text.lstrip('\ufeff')),delimiter=';'))
    assert 'Inter Empresas' in rows[0][0] and rows[-1][1]=='800,00'
    assert response.headers['cache-control']=='private, no-store'
