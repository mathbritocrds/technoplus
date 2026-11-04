"""Brazilian monthly payroll calculations. Monetary operations use Decimal."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

D = lambda value: Decimal(str(value))
ZERO = D(0)
RULES_VERSION = 'BR-2026.3'
CALCULATION_VERSION = 'PAYROLL-2026.4'
PROFILE_DEFAULTS = dict(hired_on='', terminated_on='', dependents=0, alimony=0,
    other_deductions=0, vt_amount=0, vt_rate=.06, va_amount=0, va_discount=0,
    fgts_rate=.08, employer_rate=.20, vacation_days=30, variable_average=0, pay_basis='monthly', hourly_rate=0,
    reference_monthly_hours=0, weekly_workdays=6, payroll_holidays='')


def money(value):
    return float(D(value).quantize(D('.01'), rounding=ROUND_HALF_UP))


def validate_month(month):
    if len(month) != 7 or month[4] != '-':
        raise ValueError('Competência inválida. Use AAAA-MM.')
    start = date.fromisoformat(month + '-01')
    return start, date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])


def tax_rules(month, tax_table=None):
    start, _ = validate_month(month)
    if tax_table is not None:
        return tax_table
    if start.year != 2026:
        raise ValueError('Tabela fiscal não cadastrada para esta competência. Disponível: 2026.')
    return {'version': RULES_VERSION,
        'inss': [(1621, .075), (2902.84, .09), (4354.27, .12), (8475.55, .14)],
        'inss_offsets': [0, 24.32, 111.40, 198.49], 'inss_max': 988.09,
        'inss_method': 'progressive',
        'irrf': [(2428.80, 0, 0), (2826.65, .075, 182.16),
                 (3751.05, .15, 394.16), (4664.68, .225, 675.49), (None, .275, 908.73)],
        'dependent_deduction': 189.59, 'simplified_deduction': 607.20}


def inss(gross, month='2026-01', tax_table=None):
    total, previous = ZERO, ZERO
    for ceiling, rate in tax_rules(month, tax_table)['inss']:
        taxable = max(ZERO, min(D(gross), D(ceiling)) - previous)
        total += taxable * D(rate)
        previous = D(ceiling)
    return min(money(total), tax_rules(month, tax_table)['inss_max'])


def irrf(gross, contribution, profile, month, tax_table=None):
    rules = tax_rules(month, tax_table)
    legal = D(contribution) + D(profile['dependents']) * D(rules['dependent_deduction']) + D(profile['alimony']) + D(profile['other_deductions'])
    deduction = max(legal, D(rules['simplified_deduction']))
    base = max(ZERO, D(gross) - deduction)
    for ceiling, rate, offset in rules['irrf']:
        if ceiling is None or base <= D(ceiling):
            tax = max(ZERO, base * D(rate) - D(offset))
            break
    reduction = (min(tax, D(rules.get('irrf_reduction_full_amount', 312.89)))
                 if D(gross) <= D(rules.get('irrf_reduction_full_limit', 5000)) else
                 min(tax, max(ZERO, D(rules.get('irrf_reduction_taper_offset', 978.62)) -
                     D(rules.get('irrf_reduction_taper_rate', .133145)) * D(gross)))
                 if D(gross) <= D(rules.get('irrf_reduction_taper_limit', 7350)) else ZERO)
    return {'irrf': money(tax - reduction), 'irrf_base': money(base),
            'irrf_deduction': money(deduction), 'irrf_reduction': money(reduction),
            'irrf_method': 'legal' if legal >= D(rules['simplified_deduction']) else 'simplified'}


def anniversary(start, years):
    return start.replace(year=start.year + years, day=min(start.day, calendar.monthrange(start.year + years, start.month)[1]))


def vacation_service_avos(hired, as_of):
    """Completed service months plus a remaining fraction of at least 15 days."""
    if as_of < hired:
        return 0
    months=(as_of.year-hired.year)*12+as_of.month-hired.month
    def anchor(number):
        year,month=divmod(hired.year*12+hired.month-1+number,12)
        return date(year,month+1,min(hired.day,calendar.monthrange(year,month+1)[1]))
    if anchor(months)>as_of:
        months-=1
    return months+int((as_of-anchor(months)).days+1>=15)


def entitlement(profile, as_of, records):
    """Vacation cycles use anniversaries, rather than calendar-year months."""
    hired = date.fromisoformat(profile['hired_on']) if profile['hired_on'] else None
    if not hired or hired > as_of:
        return {'vacation_cycles': [], 'vacation_proportional': 0, 'vacation_total': 0, 'vacation_months': 0}
    if profile.get('terminated_on'):
        as_of = min(as_of, date.fromisoformat(profile['terminated_on']))
    cycles, year = [], 0
    remuneration = D(profile.get('remuneration', 0))
    while anniversary(hired, year + 1) <= as_of:
        start, end = anniversary(hired, year), anniversary(hired, year + 1)
        taken = sum(r['days'] for r in records if r['acquisition_start'] == start.isoformat())
        days = max(0, profile['vacation_days'] - taken)
        overdue = as_of >= anniversary(hired, year + 2)
        amount = money(remuneration * D(days) / 30 * D(4) / 3 * (2 if overdue else 1))
        cycles.append({'start': start.isoformat(), 'end': (end-timedelta(days=1)).isoformat(),
                       'remaining_days': days, 'overdue': overdue, 'amount': amount,
                       'concession_deadline': (anniversary(hired,year+2)-timedelta(days=1)).isoformat()})
        year += 1
    months = max(0,min(12,vacation_service_avos(hired,as_of)-year*12))
    proportional = money(remuneration * D(profile['vacation_days']) / 30 * D(months) / 12 * D(4) / 3)
    return {'vacation_cycles': cycles, 'vacation_proportional': proportional,
            'vacation_total': money(D(proportional) + sum((D(c['amount']) for c in cycles), ZERO)), 'vacation_months': months}


def contract_hourly_rate(employee, profile, divisor=220):
    return D(profile['hourly_rate']) if profile.get('pay_basis')=='hourly' else D(employee['salary'])/D(divisor)


def remuneration_reference(employee, profile, salary_hour_divisor=220):
    p={**PROFILE_DEFAULTS,**profile}
    base=(D(p['hourly_rate'])*D(p['reference_monthly_hours'] or salary_hour_divisor)
          if p['pay_basis']=='hourly' else D(employee['salary']))
    return base+D(p['variable_average'])


def calculate(employee, profile, month, overtime_hours=0, records=(), bonus_amount=0, *,
              salary_hour_divisor=220, overtime_multiplier=1.5, tax_table=None, worked_hours=0):
    start, end = validate_month(month)
    rules = tax_rules(month, tax_table)
    if D(worked_hours)<0 or D(overtime_hours)<0:
        raise ValueError('Horas trabalhadas e extras não podem ser negativas.')
    if D(salary_hour_divisor) <= 0 or D(overtime_multiplier) < 1:
        raise ValueError('Divisor de horas e adicional de horas extras inválidos.')
    p = {**PROFILE_DEFAULTS, **profile}
    hired = date.fromisoformat(p['hired_on']) if p['hired_on'] else start.replace(month=1)
    terminated = date.fromisoformat(p['terminated_on']) if p['terminated_on'] else end
    days = max(0, (min(end, terminated)-max(start, hired)).days+1)
    fraction = D(1) if days == (end-start).days+1 else min(D(1), D(days)/30)
    hourly=p['pay_basis']=='hourly'
    if hourly and D(p['hourly_rate'])<=0:
        raise ValueError('Informe um valor de hora positivo para o horista.')
    salary = (D(p['hourly_rate'])*D(p['reference_monthly_hours'] or salary_hour_divisor)
              if hourly else D(employee['salary']))
    hourly_rate=contract_hourly_rate(employee,p,salary_hour_divisor)
    regular_hours=max(ZERO,D(worked_hours)-D(overtime_hours))
    ot = D(money(D(overtime_hours) * hourly_rate * D(overtime_multiplier))) if days else ZERO
    base_pay=D(money(regular_hours*hourly_rate if hourly and days else salary*fraction))
    workdays=rest_days=0
    dsr=ZERO
    if hourly and days:
        holidays={date.fromisoformat(value.strip()) for value in p['payroll_holidays'].split(',') if value.strip()}
        day=max(start,hired)
        while day<=min(end,terminated):
            if day.weekday()==6 or day in holidays:
                rest_days+=1
            elif day.weekday()<p['weekly_workdays']:
                workdays+=1
            day+=timedelta(days=1)
        dsr=D(money((base_pay+ot)*rest_days/workdays)) if workdays else ZERO
    bonus = D(money(bonus_amount)) if days else ZERO
    gross = D(money(base_pay + ot + dsr + bonus))
    contribution = inss(gross, month, rules)
    taxes = irrf(gross, contribution, p, month, rules)
    vt = D(money(D(p['vt_amount']) * fraction))
    va = D(money(D(p['va_amount']) * fraction))
    vt_base=(base_pay+(D(money(base_pay*rest_days/workdays)) if workdays else ZERO)) if hourly else salary*fraction
    vt_discount = D(money(min(vt, vt_base * D(p['vt_rate']))))
    va_discount = D(money(min(va, D(p['va_discount']) * fraction)))
    benefit_cash = D(money(D(employee['benefits']) * fraction))
    fgts = D(money(gross * D(p['fgts_rate'])))
    employer = D(money(gross * D(p['employer_rate'])))
    thirteenth_months = sum((min(date(start.year, m, calendar.monthrange(start.year,m)[1]), end, terminated) - max(date(start.year,m,1), hired)).days+1 >= 15 for m in range(1, start.month+1)) if p['hired_on'] else 0
    remuneration = remuneration_reference(employee,p,salary_hour_divisor)
    thirteenth_avo = int(bool(p['hired_on']) and days >= 15)
    vacation_avo = max(0,vacation_service_avos(hired,min(end,terminated))-
        vacation_service_avos(hired,min(start-timedelta(days=1),terminated))) if p['hired_on'] else 0
    thirteenth_provision = D(money(remuneration * thirteenth_avo / 12))
    vacation_base = D(money(remuneration * D(p['vacation_days']) / 30 * vacation_avo / 12))
    vacation_third = D(money(vacation_base / 3))
    vacation_provision = vacation_base + vacation_third
    provision_charges = D(money((thirteenth_provision+vacation_provision) * (D(p['fgts_rate'])+D(p['employer_rate']))))
    vacation_salary_offset = vacation_base
    vacation_charge_offset = D(money(vacation_salary_offset * (D(p['fgts_rate'])+D(p['employer_rate']))))
    cash_cost = gross + benefit_cash + vt-vt_discount + va-va_discount + fgts + employer
    result = {'id': employee['id'], 'name': employee['name'], 'role': employee['role'], 'department_id': employee['department_id'],
        'pay_basis':p['pay_basis'], 'base_pay':float(base_pay), 'dsr_pay':float(dsr),
        'dsr_workdays':workdays,'dsr_rest_days':rest_days,'calculation_version':CALCULATION_VERSION,
        'base_salary': float(salary), 'bonus_amount': float(bonus), 'gross': float(gross), 'overtime_hours': overtime_hours,
        'overtime_pay': float(ot), 'inss': contribution, **taxes, 'benefits': float(benefit_cash),
        'vt_amount': float(vt), 'vt_discount': float(vt_discount), 'va_amount': float(va), 'va_discount': float(va_discount),
        'fgts': float(fgts), 'employer_charges': float(employer),
        'net': money(gross-D(contribution)-D(taxes['irrf'])-D(p['alimony'])-vt_discount-va_discount+benefit_cash),
        'company_cost': money(cash_cost), 'accrual_cost': money(cash_cost+thirteenth_provision+vacation_provision+provision_charges-vacation_salary_offset-vacation_charge_offset),
        'worked_hours': round(float(worked_hours),4), 'regular_hours': round(max(0,float(worked_hours)-float(overtime_hours)),4),
        'contract_hourly_rate': money(hourly_rate),
        'cost_per_worked_hour': money((cash_cost+thirteenth_provision+vacation_provision+provision_charges-vacation_salary_offset-vacation_charge_offset)/D(worked_hours)) if D(worked_hours)>0 else None,
        'thirteenth_base': float(remuneration), 'thirteenth_avo_earned': thirteenth_avo, 'vacation_avo_earned': vacation_avo,
        'vacation_base_provision': float(vacation_base), 'vacation_third_provision': float(vacation_third),
        'thirteenth_months': thirteenth_months, 'thirteenth_proportional': money(remuneration*D(thirteenth_months)/12),
        'thirteenth_provision': float(thirteenth_provision), 'vacation_provision': float(vacation_provision),
        'vacation_salary_offset': float(vacation_salary_offset), 'vacation_charge_offset': float(vacation_charge_offset), 'provision_charges': float(provision_charges), 'rules_version': rules['version'],
        'profile_complete': bool(p['hired_on']), 'calculation_profile': {k: p[k] for k in PROFILE_DEFAULTS}}
    result.update(entitlement({**p, 'remuneration': float(remuneration)}, min(end, terminated), records))
    return result
