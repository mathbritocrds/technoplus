"""Real calculation examples for hours, annual deductions and the supplied DRE model."""
import json
from datetime import date
from decimal import Decimal
import pytest
from app import main,payroll as hr
from tests.test_employee_rename import service,employee
from tests.test_dre_xlsx import sheet,value


def person(salary=3000):
    return dict(id=1,name='Ana',role='',department_id=None,salary=salary,benefits=0)


def pair(eid,day,start=9,end=17,accepted=1):
    with main.db() as c:
        for kind,hour in [('entrada',start),('saida',end)]:
            c.execute('INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,?,?,?)',
                (eid,kind,f'{day}T{hour:02d}:00:00-03:00',accepted))


def test_monthly_salary_remains_fixed_and_hour_cost_is_nullable():
    zero=hr.calculate(person(),{'hired_on':'2024-01-01'},'2026-02')
    hours=hr.calculate(person(),{'hired_on':'2024-01-01'},'2026-02',worked_hours=8)
    assert zero['gross']==hours['gross']==3000
    assert zero['cost_per_worked_hour'] is None
    assert hours['worked_hours']==8
    assert hours['cost_per_worked_hour']==hr.money(Decimal(str(hours['accrual_cost']))/8)


@pytest.mark.parametrize('workdays,holidays,expected_dsr',[(6,'',36.67),(6,'2026-02-08',36.67),
    (6,'2026-02-16,2026-02-16',47.83),(5,'2026-02-16',57.89)])
def test_hourly_pay_splits_regular_overtime_and_calendar_dsr(workdays,holidays,expected_dsr):
    profile=dict(hired_on='2024-01-01',pay_basis='hourly',hourly_rate=20,
        reference_monthly_hours=160,weekly_workdays=workdays,payroll_holidays=holidays)
    result=hr.calculate(person(9999),profile,'2026-02',worked_hours=10,overtime_hours=2)
    assert result['base_pay']==160 and result['overtime_pay']==60
    assert result['dsr_pay']==expected_dsr
    assert result['gross']==hr.money(220+expected_dsr)
    assert result['inss']==hr.inss(result['gross'],'2026-02')
    assert result['thirteenth_base']==3200 and result['contract_hourly_rate']==20
    assert result['thirteenth_proportional']==533.33


def test_hourly_no_clock_hours_does_not_generate_salary_or_fake_hour_cost():
    result=hr.calculate(person(),{'hired_on':'2026-01-01','pay_basis':'hourly','hourly_rate':20},'2026-02')
    assert result['gross']==result['base_pay']==result['dsr_pay']==0
    assert result['worked_hours']==0 and result['cost_per_worked_hour'] is None


@pytest.mark.parametrize('hired,avos',[('2026-01-17',1),('2026-01-18',0)])
def test_thirteenth_fifteen_day_boundary_uses_calendar_months(hired,avos):
    result=hr.calculate(person(),{'hired_on':hired},'2026-01')
    assert result['thirteenth_months']==avos and result['thirteenth_avo_earned']==avos
    assert result['thirteenth_proportional']==3000*avos/12


def test_vacation_avos_use_service_months_and_do_not_double_count_short_february():
    profile={'hired_on':'2026-01-16'}
    january=hr.calculate(person(),profile,'2026-01')
    february=hr.calculate(person(),profile,'2026-02')
    march=hr.calculate(person(),profile,'2026-03')
    assert [row['vacation_avo_earned'] for row in (january,february,march)]==[1,0,2]
    assert february['vacation_months']==1 and february['vacation_proportional']==333.33
    assert february['thirteenth_months']==2 and february['thirteenth_proportional']==500
    assert february['vacation_provision']==0 and february['thirteenth_provision']==250
    assert hr.vacation_service_avos(date(2024,2,29),date(2025,2,28))==12


def test_missing_admission_does_not_invent_vacation_or_thirteenth_entitlement():
    result=hr.calculate(person(),{},'2026-12')
    assert not result['profile_complete']
    assert result['thirteenth_months']==result['thirteenth_proportional']==result['vacation_total']==0
    assert result['thirteenth_provision']==result['vacation_provision']==0


@pytest.mark.parametrize('starts,days,late,expected',[('2025-12-20',20,8,3733.33),
    ('2026-01-01',30,30,8000),('2025-12-01',20,0,2666.67)])
def test_vacation_quote_only_doubles_days_after_concession_deadline(service,starts,days,late,expected):
    client,auth=service;eid=employee(service)
    client.put(f'/employees/{eid}/payroll-profile',headers=auth,json={'hired_on':'2024-01-01'})
    response=client.post(f'/employees/{eid}/vacations/quote',headers=auth,json={
        'acquisition_start':'2024-01-01','starts_on':starts,'days':days})
    assert response.status_code==200,response.text
    quote=response.json()
    assert quote['overdue_days']==late and quote['gross']==expected
    assert quote['regular_days']==days-late and quote['concession_deadline']=='2025-12-31'


def test_hourly_profile_persists_point_payroll_and_holiday_validation(service):
    client,auth=service;eid=employee(service)
    profile={'hired_on':'2026-02-01','pay_basis':'hourly','hourly_rate':20,'reference_monthly_hours':160}
    assert client.put(f'/employees/{eid}/payroll-profile',headers=auth,json=profile).status_code==200
    saved=client.get(f'/employees/{eid}/payroll-profile',headers=auth).json()
    assert saved['pay_basis']=='hourly' and saved['hourly_rate']==20
    pair(eid,'2026-02-02',9,19)
    pair(eid,'2026-02-03',9,19,accepted=0)
    with main.db() as c:
        c.execute("INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,'entrada','2026-02-04T09:00:00-03:00',1)",(eid,))
    result=client.get('/payroll?month=2026-02',headers=auth).json()['employees'][0]
    assert result['worked_hours']==10 and result['overtime_hours']==2
    assert result['gross']==256.67 and result['base_pay']==160
    assert client.put(f'/employees/{eid}/payroll-profile',headers=auth,json={**profile,'hourly_rate':0}).status_code==422
    assert client.put(f'/employees/{eid}/payroll-profile',headers=auth,json={**profile,'payroll_holidays':'2026-02-31'}).status_code==422


def test_annual_inss_hours_and_closed_snapshot_are_consistent(service):
    client,auth=service;eid=employee(service)
    pair(eid,'2026-02-02')
    monthly=client.get('/payroll?month=2026-02',headers=auth).json()['employees'][0]
    assert client.post('/payroll/close',headers=auth,json={'month':'2026-02'}).status_code==200
    with main.db() as c:
        snapshot=c.execute('SELECT snapshot FROM payroll_items').fetchone()[0]
    annual=client.get('/payroll/annual-cost?year=2026',headers=auth).json()['employees'][0]
    assert annual['inss']==hr.money(Decimal(str(monthly['inss']))*12)
    assert annual['worked_hours']==8 and annual['months_with_recorded_hours']==1
    assert annual['cost_per_worked_hour']==hr.money(Decimal(str(monthly['accrual_cost']))/8)
    assert annual['total']==pytest.approx(annual['salary']+annual['benefits']+annual['fgts']+annual['employer_charges']+annual['provisions'],abs=.01)
    pair(eid,'2026-02-03')
    after=client.get('/payroll/annual-cost?year=2026',headers=auth).json()['employees'][0]
    assert after['worked_hours']==8 and after['inss']==annual['inss']
    with main.db() as c:
        assert c.execute('SELECT snapshot FROM payroll_items').fetchone()[0]==snapshot


def test_dre_inter_rows_match_export_and_category_filter_does_not_change_result(service):
    client,auth=service
    for category,amount in [('revenue',10000),('tax',500),('cost',1500),('operating',800),('personnel',2000),('financial',200)]:
        payload={'kind':'receber' if category=='revenue' else 'pagar','description':'Lançamento','amount':amount,
            'due':'2026-06-10','category':'operating' if category=='revenue' else category}
        assert client.post('/finance',headers=auth,json=payload).status_code==201
    full=client.get('/finance/dre?start=2026-01&end=2026-12',headers=auth).json()
    filtered=client.get('/finance/dre?start=2026-01&end=2026-12&category=operating',headers=auth).json()
    assert filtered['inter_model']==full['inter_model']
    model=full['inter_model'];rows={row['key']:row for row in model['rows']}
    assert len(model['months'])==12 and rows['operating_expenses']['amount']==2800
    assert rows['financial_result']['amount']==-200
    assert rows['net_profit']['amount']==rows['net_profit']['months']['2026-06']==5000
    exported=client.get('/finance/dre/modelo.xlsx?start=2026-01&end=2026-12',headers=auth)
    assert exported.status_code==200
    assert value(sheet(exported,3),'C40')==Decimal(str(rows['net_profit']['amount']))
    assert rows['net_profit']['revenue_pct']==50
    annual_cells=sheet(exported,3)
    for rubric in model['rubrics']:
        assert value(annual_cells,'C'+str(rubric['excel_row']))==Decimal(str(rubric['amount']))


def test_hourly_transport_discount_uses_basic_pay_not_monthly_reference_or_overtime():
    result=hr.calculate(person(9999),{'hired_on':'2024-01-01','pay_basis':'hourly',
        'hourly_rate':20,'reference_monthly_hours':160,'vt_amount':150},'2026-02',worked_hours=10,overtime_hours=2)
    assert result['vt_discount']==11.20


def test_hourly_pay_ignores_clock_hours_outside_the_contract(service):
    client,auth=service;eid=employee(service)
    assert client.put(f'/employees/{eid}/payroll-profile',headers=auth,json={
        'hired_on':'2026-02-10','terminated_on':'2026-02-20','pay_basis':'hourly','hourly_rate':20}).status_code==200
    pair(eid,'2026-02-02',9,19)
    pair(eid,'2026-02-11',9,19)
    pair(eid,'2026-02-23',9,19)
    result=client.get('/payroll?month=2026-02',headers=auth).json()['employees'][0]
    assert result['worked_hours']==10 and result['overtime_hours']==2
    assert result['thirteenth_months']==0
