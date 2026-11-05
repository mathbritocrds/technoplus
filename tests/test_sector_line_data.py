"""Annual sector lines follow each month's actual department, including frozen payroll."""
import pytest
from app import main
from tests.test_employee_rename import service,employee


def test_annual_sector_composition_reconciles_and_retains_closed_sector_on_transfer(service):
    client,auth=service
    first=client.post('/departments',headers=auth,json={'name':'Produção'}).json()['id']
    second=client.post('/departments',headers=auth,json={'name':'Comercial'}).json()['id']
    eid=employee(service,department_id=first)
    january=client.get('/payroll?month=2026-01',headers=auth).json()['employees'][0]
    assert client.post('/payroll/close',headers=auth,json={'month':'2026-01'}).status_code==200
    assert client.patch(f'/employees/{eid}',headers=auth,json={'department_id':second}).status_code==200
    annual=client.get('/payroll/annual-cost?year=2026',headers=auth).json()
    sectors={row['department_id']:row for row in annual['department_composition']}
    assert sectors[first]['total']==january['accrual_cost']
    assert sectors[second]['total']==pytest.approx(january['accrual_cost']*11,abs=.02)
    assert sum(row['total'] for row in sectors.values())==pytest.approx(annual['total_cost'],abs=.01)
    assert sum(row['net_total'] for row in sectors.values())==pytest.approx(annual['total_net'],abs=.01)
    for sector in sectors.values():
        assert sector['total']==pytest.approx(sum(sector[key] for key in ('salary','benefits','fgts','employer_charges','provisions')),abs=.01)
