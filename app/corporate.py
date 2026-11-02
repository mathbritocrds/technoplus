"""Audited administrative workflows; external receipts are evidence, not API submissions."""
import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from app import accounting, business, payroll as hr
from app.financial_controls import ensure_open
from app.tax_registry import approve_table, get_tax_rules


class Reason(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class Period(Reason):
    month: str


class Complement(Period):
    reference: str = Field(min_length=8, max_length=120)
    booked_on: date


class ObligationGeneration(Period):
    due: date


class Statement(BaseModel):
    account: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=1_000_000)


class Match(Reason):
    payment_id: int


class Evidence(Period):
    kind: Literal['esocial','fgts','inss','irrf','vacation','thirteenth','termination','benefits_and_other']
    reference: str = Field(min_length=5, max_length=200)
    evidence: str = Field(min_length=5, max_length=2000)


class TaxApproval(BaseModel):
    year: int = Field(ge=2026, le=2100)
    source: str = Field(min_length=10, max_length=2000)
    table: dict
    reason: str = Field(min_length=10, max_length=1000)


class Policy(BaseModel):
    vacation_rest_weekdays: list[int] = Field(default=[6], min_length=1, max_length=7)
    vacation_holidays: list[date] = Field(default=[], max_length=200)
    external_payroll_provider: str = Field(min_length=3, max_length=200)
    reviewed_regime: str = Field(min_length=3, max_length=200)
    reviewed_agreement: str = Field(min_length=3, max_length=200)
    reason: str = Field(min_length=10, max_length=1000)


def reason_text(value):
    value = value.strip()
    if len(value) < 5:
        raise HTTPException(422, 'Informe uma justificativa com pelo menos cinco caracteres.')
    return value


def obligation_status(m,c,month):
    if not c.execute('SELECT 1 FROM payroll_runs WHERE month=?',(month,)).fetchone():
        return {'month':month,'closed':False,'items':[]}
    employees=business.payroll_data(m,month,c)['employees']
    groups={}
    for employee in employees:
        groups.setdefault(employee['department_id'],[]).append(employee)
    items=[]
    for department,staff in groups.items():
        totals={key:sum((hr.D(e[key]) for e in staff),hr.ZERO) for key in ('inss','irrf','fgts','employer_charges')}
        liability=sum((hr.D(e['company_cost'])-hr.D(e['net']) for e in staff),hr.ZERO)
        remainder=liability-sum(totals.values(),hr.ZERO)
        if remainder < hr.D('-.01'):
            raise HTTPException(409,'Obrigações inconsistentes. Revise a folha antes de gerar recolhimentos.')
        totals['benefits_and_other']=max(hr.ZERO,remainder)
        for kind,calculated in totals.items():
            transactions=m.rows(c.execute('SELECT id,kind,amount,paid,due FROM transactions WHERE source_key LIKE ?', (f'payroll:obligation:{month}:{department or 0}:{kind}:%',)))
            generated=sum((hr.D(row['amount'])*(1 if row['kind']=='pagar' else -1) for row in transactions),hr.ZERO)
            paid=sum((hr.D(row['amount'])*(1 if row['kind']=='pagar' else -1) for row in transactions if row['paid']),hr.ZERO)
            items.append({'kind':kind,'department_id':department,'calculated':hr.money(calculated),'generated':hr.money(generated),'paid':hr.money(paid),'transactions':transactions})
    return {'month':month,'closed':True,'items':items,'notice':'Vencimentos e guias devem ser conferidos pelo responsável fiscal. A geração não efetua recolhimento.'}


def register_routes(m):
    app = m.app

    @app.get('/accounting/periods')
    def periods(who=Depends(m.admin_context)):
        with m.db() as c:
            return m.rows(c.execute('SELECT * FROM accounting_periods ORDER BY month DESC'))

    @app.post('/accounting/periods/close')
    def close_period(payload: Period, who=Depends(m.admin_context)):
        month = business.month_or_error(payload.month)
        reason = reason_text(payload.reason)
        if month > m.local(m.utcnow()).strftime('%Y-%m'):
            raise HTTPException(400, 'Não encerre uma competência futura.')
        with m.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM accounting_periods WHERE month=?', (month,)).fetchone()
            if old and old['closed']:
                return {'month': month, 'already_closed': True}
            # Closing requires explicit reconciliation of every imported statement
            # entry and payment of the month; there is no implicit bank confirmation.
            unmatched = c.execute('SELECT 1 FROM bank_entries e LEFT JOIN bank_matches b ON b.bank_entry_id=e.id WHERE substr(e.booked_on,1,7)=? AND b.id IS NULL LIMIT 1', (month,)).fetchone()
            payments = any(
                m.local(datetime.fromisoformat(row['paid_at'])).strftime('%Y-%m') == month
                for row in c.execute('SELECT p.paid_at FROM payment_history p LEFT JOIN bank_matches b ON b.payment_id=p.id WHERE b.id IS NULL'))
            if unmatched or payments:
                raise HTTPException(409, 'Concilie os pagamentos e as linhas de extrato antes de encerrar a contabilidade.')
            start, end = hr.validate_month(month)
            eligible = c.execute("SELECT 1 FROM employees e LEFT JOIN employee_payroll_profiles p ON p.employee_id=e.id WHERE (e.active=1 OR COALESCE(p.terminated_on,'')<>'') AND (COALESCE(p.hired_on,'')='' OR p.hired_on<=?) AND (COALESCE(p.terminated_on,'')='' OR p.terminated_on>=?) LIMIT 1", (str(end),str(start))).fetchone()
            if eligible and not c.execute('SELECT 1 FROM payroll_runs WHERE month=?',(month,)).fetchone():
                raise HTTPException(409,'Feche a folha dos funcionários elegíveis antes de encerrar a contabilidade.')
            totals = accounting.report(m, c, str(start), str(end), None)
            if not totals['trial']['balanced']:
                raise HTTPException(409, 'Balancete não está equilibrado.')
            c.execute('INSERT INTO accounting_periods(month,closed,closed_at,closed_by,reason) VALUES(?,1,?,?,?) ON CONFLICT(month) DO UPDATE SET closed=1,closed_at=excluded.closed_at,closed_by=excluded.closed_by,reason=excluded.reason',
                      (month, m.iso(m.utcnow()), who['user'], reason))
            accounting.event(m,c,who,'accounting_period',month,dict(old) if old else {},{'closed':True},reason)
        return {'month':month,'already_closed':False}

    @app.post('/accounting/periods/reopen')
    def reopen_period(payload: Period, who=Depends(m.admin_context)):
        month = business.month_or_error(payload.month)
        reason = reason_text(payload.reason)
        with m.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM accounting_periods WHERE month=?', (month,)).fetchone()
            if not old or not old['closed']:
                raise HTTPException(409, 'Competência não está encerrada.')
            c.execute('UPDATE accounting_periods SET closed=0 WHERE month=?', (month,))
            accounting.event(m,c,who,'accounting_period',month,dict(old),{'closed':False},reason)
        return {'month':month,'closed':False}

    @app.get('/accounting/bank-entries')
    def bank_entries(month: str, who=Depends(m.admin_context)):
        business.month_or_error(month)
        with m.db() as c:
            return m.rows(c.execute('SELECT e.*,b.payment_id FROM bank_entries e LEFT JOIN bank_matches b ON b.bank_entry_id=e.id WHERE substr(e.booked_on,1,7)=? ORDER BY e.booked_on,e.id', (month,)))

    @app.post('/accounting/bank-entries/import')
    def import_statement(payload: Statement, who=Depends(m.admin_context)):
        account = payload.account.strip()
        if not account:
            raise HTTPException(422, 'Informe a identificação da conta bancária.')
        reader = csv.DictReader(io.StringIO(payload.content.lstrip('\ufeff')), delimiter=';')
        if not reader.fieldnames or not {'reference','date','amount','description'}.issubset(reader.fieldnames):
            raise HTTPException(422, 'CSV obrigatório: reference;date;amount;description. Valores assinados, ponto decimal.')
        lines = []
        try:
            for i, row in enumerate(reader, 2):
                if i > 2001:
                    raise ValueError('Limite de 2.000 linhas.')
                stamp = date.fromisoformat(row['date'])
                amount = Decimal(row['amount'])
                if not amount.is_finite() or amount == 0 or amount != amount.quantize(Decimal('.01')) or abs(amount) > Decimal('999999999999'):
                    raise ValueError('Valor deve ser não zero, finito e em centavos exatos.')
                reference = row['reference'].strip()
                if not reference or len(reference)>200 or len(row['description'])>1000:
                    raise ValueError('Referência ou descrição inválida.')
                lines.append((reference,str(stamp),int(amount*100),row['description']))
        except (ValueError, InvalidOperation, TypeError, KeyError) as exc:
            raise HTTPException(422, f'Linha {i}: {exc}')
        if not lines:
            raise HTTPException(422, 'Extrato vazio.')
        with m.db() as c:
            c.execute('BEGIN IMMEDIATE')
            inserted=0
            for reference, stamp, amount, description in lines:
                existing = c.execute('SELECT * FROM bank_entries WHERE account=? AND reference=?', (account,reference)).fetchone()
                if existing:
                    if (existing['booked_on'],existing['amount_cents'],existing['description']) != (stamp,amount,description):
                        raise HTTPException(409, 'Referência bancária já importada com outro conteúdo.')
                    continue
                ensure_open(c,stamp)
                c.execute('INSERT INTO bank_entries(account,reference,booked_on,amount_cents,description,imported_at,imported_by) VALUES(?,?,?,?,?,?,?)',
                          (account,reference,stamp,amount,description,m.iso(m.utcnow()),who['user']))
                inserted+=1
            accounting.event(m,c,who,'bank_import',account,{}, {'inserted':inserted},'Importação de extrato por arquivo')
        return {'inserted':inserted,'total':len(lines)}

    @app.post('/accounting/bank-entries/{entry_id}/match')
    def match_payment(entry_id:int,payload:Match,who=Depends(m.admin_context)):
        reason=reason_text(payload.reason)
        with m.db() as c:
            c.execute('BEGIN IMMEDIATE')
            entry=c.execute('SELECT * FROM bank_entries WHERE id=?',(entry_id,)).fetchone()
            payment=c.execute('SELECT * FROM payment_history WHERE id=?',(payload.payment_id,)).fetchone()
            if not entry or not payment:
                raise HTTPException(404,'Linha de extrato ou pagamento não encontrado.')
            previous=c.execute('SELECT * FROM bank_matches WHERE bank_entry_id=? OR payment_id=?',(entry_id,payload.payment_id)).fetchone()
            if previous:
                if previous['bank_entry_id']==entry_id and previous['payment_id']==payload.payment_id:
                    return {'id':previous['id'],'already_matched':True}
                raise HTTPException(409,'Linha ou pagamento já conciliado com outro registro.')
            ensure_open(c,entry['booked_on'])
            signed=accounting.cents(payment['amount'])*(1 if payment['kind']=='receber' else -1)
            if signed!=entry['amount_cents']:
                raise HTTPException(409,'Valor ou sentido do extrato difere do pagamento.')
            if abs((date.fromisoformat(entry['booked_on'])-m.local(datetime.fromisoformat(payment['paid_at'])).date()).days)>10:
                raise HTTPException(409,'Datas distam mais de dez dias; revise o pagamento e o extrato.')
            mid=c.execute('INSERT INTO bank_matches(bank_entry_id,payment_id,reason,matched_at,matched_by) VALUES(?,?,?,?,?) RETURNING id',
                          (entry_id,payload.payment_id,reason,m.iso(m.utcnow()),who['user'])).fetchone()['id']
            accounting.event(m,c,who,'bank_match',mid,{}, {'bank_entry_id':entry_id,'payment_id':payload.payment_id},reason)
        return {'id':mid,'already_matched':False}

    @app.get('/payroll/adjustments')
    def adjustments(month:str,who=Depends(m.admin_context)):
        business.month_or_error(month)
        with m.db() as c:
            return m.rows(c.execute('SELECT id,month,reference,reason,booked_on,created_at,created_by,delta_json FROM payroll_adjustments WHERE month=? ORDER BY id',(month,)))

    @app.post('/payroll/adjustments')
    def create_adjustment(payload:Complement,who=Depends(m.admin_context)):
        month=business.month_or_error(payload.month)
        reason=reason_text(payload.reason)
        with m.db() as c:
            c.execute('BEGIN IMMEDIATE')
            existing=c.execute('SELECT * FROM payroll_adjustments WHERE reference=?',(payload.reference,)).fetchone()
            if existing:
                if (existing['month'],existing['reason'],existing['booked_on']) != (month,reason,str(payload.booked_on)):
                    raise HTTPException(409,'Referência de complemento já usada com outro conteúdo.')
                return {'id':existing['id'],'already_created':True}
            if not c.execute('SELECT 1 FROM payroll_runs WHERE month=?',(month,)).fetchone():
                raise HTTPException(409,'Feche a folha original antes de registrar um complemento.')
            if payload.booked_on < hr.validate_month(month)[0] or payload.booked_on>m.local(m.utcnow()).date():
                raise HTTPException(422,'Data do complemento deve estar entre a competência original e hoje.')
            ensure_open(c,payload.booked_on)
            old=business.payroll_data(m,month,c)
            live=business.payroll_data(m,month,c,live=True)
            if not live['employees'] or any(not e['profile_complete'] or e['net']<0 for e in live['employees']):
                raise HTTPException(409,'Regularize os cadastros e líquidos antes da complementação.')
            attendance=m.timesheet_data(c,month)
            if any(r.get('open') or r.get('pending_entry_ids') or r.get('anomalies') for r in attendance.values()):
                raise HTTPException(409,'Regularize as pendências do ponto antes da complementação.')
            before={e['id']:e for e in old['employees']};current={e['id']:e for e in live['employees']}
            # Retroactive corrections retain the original period's cost center.
            # A later transfer must never reclassify the original payroll.
            for eid, item in current.items():
                if eid in before:
                    item['department_id'] = before[eid]['department_id']
            if set(before)-set(current):
                raise HTTPException(409,'Funcionário da folha original ausente no recálculo; regularize seu vínculo antes de complementar.')
            deltas=[]
            fields=('net','fgts','inss','irrf','employer_charges','company_cost','accrual_cost')
            for eid,item in current.items():
                previous=before.get(eid,{})
                delta={field:hr.money(hr.D(item[field])-hr.D(previous.get(field,0))) for field in fields}
                if any(delta.values()):
                    deltas.append({'id':eid,'name':item['name'],'department_id':item['department_id'],**delta})
            if not deltas:
                raise HTTPException(409,'Não há diferenças financeiras para complementar.')
            aid=c.execute('INSERT INTO payroll_adjustments(month,reference,reason,booked_on,created_at,created_by,current_json,delta_json) VALUES(?,?,?,?,?,?,?,?) RETURNING id',
                          (month,payload.reference,reason,str(payload.booked_on),m.iso(m.utcnow()),who['user'],json.dumps(live['employees']),json.dumps(deltas))).fetchone()['id']
            for delta in deltas:
                net=delta['net']
                if net:
                    c.execute('INSERT INTO transactions(kind,description,amount,due,department_id,category,competence,source_key) VALUES(?,?,?,?,?,?,?,?)',
                              ('pagar' if net>0 else 'receber',f"Complemento {month} · {delta['name']}",abs(net),str(payload.booked_on),delta['department_id'],'personnel',month,f"payroll:adjustment:{aid}:{delta['id']}"))
                total=accounting.cents(delta['accrual_cost']);cash=accounting.cents(delta['company_cost']);reserve=total-cash
                lines=[]
                for code,value in [('5.3.02',total),('2.1.03',-cash),('2.1.04',-reserve)]:
                    if value: lines.append((code,max(value,0),max(-value,0)))
                if lines:
                    accounting.post(m,c,payload.booked_on,f"Complemento · {delta['name']}",delta['department_id'],f"payroll:adjustment:{aid}:{delta['id']}",lines,who['user'])
            accounting.event(m,c,who,'payroll_adjustment',aid,{'month':month},{'deltas':deltas},reason)
        return {'id':aid,'already_created':False,'deltas':deltas}

    @app.get('/compliance/obligations')
    def obligations(month:str,who=Depends(m.admin_context)):
        business.month_or_error(month)
        with m.db() as c:
            return obligation_status(m,c,month)

    @app.post('/compliance/obligations/generate')
    def generate_obligations(payload:ObligationGeneration,who=Depends(m.admin_context)):
        month=business.month_or_error(payload.month)
        reason=reason_text(payload.reason)
        if payload.due < hr.validate_month(month)[0]:
            raise HTTPException(422,'Vencimento não pode anteceder a competência.')
        with m.db() as c:
            c.execute('BEGIN IMMEDIATE')
            ensure_open(c,payload.due)
            status=obligation_status(m,c,month)
            if not status['closed']:
                raise HTTPException(409,'Feche a folha antes de gerar recolhimentos.')
            created=[]
            for item in status['items']:
                delta=accounting.cents(item['calculated'])-accounting.cents(item['generated'])
                if not delta: continue
                prefix=f"payroll:obligation:{month}:{item['department_id'] or 0}:{item['kind']}:"
                count=c.execute('SELECT COUNT(*) FROM transactions WHERE source_key LIKE ?', (prefix+'%',)).fetchone()[0]
                tid=c.execute('INSERT INTO transactions(kind,description,amount,due,department_id,category,competence,source_key) VALUES(?,?,?,?,?,?,?,?) RETURNING id',
                    ('pagar' if delta>0 else 'receber',f"Obrigação {item['kind']} · {month}",abs(delta)/100,str(payload.due),item['department_id'],'personnel',month,prefix+str(count+1))).fetchone()['id']
                # The liability was already recognized by payroll; no new expense.
                created.append(tid)
            accounting.event(m,c,who,'payroll_obligations',month,{}, {'transaction_ids':created},reason)
        return {'created':created}

    @app.get('/compliance/tax-rules')
    def tax_tables(who=Depends(m.admin_context)):
        with m.db() as c:
            return [json.loads(row['v']) for row in c.execute("SELECT v FROM settings WHERE k LIKE 'tax_rules:%' ORDER BY k")]

    @app.post('/compliance/tax-rules')
    def approve_tax(payload:TaxApproval,who=Depends(m.admin_context)):
        with m.db() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                record=approve_table(c,payload.year,payload.table,payload.source,who['user'],m.iso(m.utcnow()))
            except ValueError as exc:
                raise HTTPException(422,str(exc))
            accounting.event(m,c,who,'tax_rules',str(payload.year),{},record,reason_text(payload.reason))
        return record

    @app.get('/compliance/policy')
    def get_policy(who=Depends(m.admin_context)):
        with m.db() as c:
            row=c.execute("SELECT v FROM settings WHERE k='compliance_policy'").fetchone()
            return json.loads(row['v']) if row else {'configured':False}

    @app.put('/compliance/policy')
    def set_policy(payload:Policy,who=Depends(m.admin_context)):
        if any(day<0 or day>6 for day in payload.vacation_rest_weekdays):
            raise HTTPException(422,'Dias de descanso devem estar entre 0 (segunda) e 6 (domingo).')
        with m.db() as c:
            data=payload.model_dump(mode='json');data.update(configured=True,reviewed_by=who['user'],reviewed_at=m.iso(m.utcnow()))
            c.execute('BEGIN IMMEDIATE')
            for key,value in [('compliance_policy',json.dumps(data)),('vacation_rest_weekdays',json.dumps(payload.vacation_rest_weekdays)),('vacation_holidays',json.dumps(data['vacation_holidays']))]:
                c.execute('INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',(key,value))
            accounting.event(m,c,who,'compliance_policy','company',{},data,reason_text(payload.reason))
        return data

    @app.post('/compliance/records')
    def external_record(payload:Evidence,who=Depends(m.admin_context)):
        business.month_or_error(payload.month);reason=reason_text(payload.reason)
        if len(payload.evidence.strip())<5 or len(payload.reference.strip())<5:
            raise HTTPException(422,'Informe o protocolo e a evidência do procedimento externo.')
        with m.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM compliance_records WHERE reference=?',(payload.reference,)).fetchone()
            if old:
                if (old['month'],old['kind'],old['evidence'],old['reason']) != (payload.month,payload.kind,payload.evidence,reason):
                    raise HTTPException(409,'Protocolo já registrado com outro conteúdo.')
                return dict(old)
            rid=c.execute('INSERT INTO compliance_records(month,kind,reference,evidence,reason,created_at,created_by) VALUES(?,?,?,?,?,?,?) RETURNING id',
                          (payload.month,payload.kind,payload.reference,payload.evidence,reason,m.iso(m.utcnow()),who['user'])).fetchone()['id']
            accounting.event(m,c,who,'compliance_record',rid,{},payload.model_dump(),reason)
        return {'id':rid}

    @app.get('/compliance/checklist')
    def checklist(month:str,who=Depends(m.admin_context)):
        business.month_or_error(month)
        with m.db() as c:
            policy=c.execute("SELECT v FROM settings WHERE k='compliance_policy'").fetchone()
            records=m.rows(c.execute('SELECT * FROM compliance_records WHERE month=? ORDER BY id',(month,)))
            run=c.execute('SELECT id FROM payroll_runs WHERE month=?',(month,)).fetchone()
            try:
                table=get_tax_rules(c,month);tax={'available':True,'version':table['version']}
            except ValueError as exc:
                tax={'available':False,'message':str(exc)}
        return {'month':month,'payroll_closed':bool(run),'tax_rules':tax,'policy':json.loads(policy['v']) if policy else {'configured':False},'records':records,
                'external_processes':['rescisão','liquidação e retenções de férias/13º','eSocial','FGTS Digital','recolhimentos e conciliação'],
                'notice':'Registros são evidências informadas pelo responsável. Não constituem transmissão governamental ou confirmação bancária automática.'}
