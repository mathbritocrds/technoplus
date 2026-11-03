"""Explicit, isolated fictitious installation. Never seeds the production database."""
import hashlib
import json
import os
import re
import secrets
import sqlite3
from html import escape
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any, Callable
from contextvars import ContextVar
from contextlib import closing
from app.services import AppServices
from threading import Lock

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse

_lock = Lock()
_initialized = {}


@dataclass(frozen=True, kw_only=True)
class DemoRuntime:
    app: FastAPI
    db: Callable[..., Any]
    production_database: Callable[[], str]
    context: ContextVar
    base_path_context: ContextVar
    SCHEMA: str
    MIGRATIONS: list[str]
    apply_sqlite_migrations: Callable[..., Any]
    hash_pin: Callable[..., str]
    local: Callable[..., datetime]
    utcnow: Callable[[], datetime]
    iso: Callable[..., str]
    entry_hash: Callable[..., str]
    services: AppServices
    APP_DIR: str
    timestamp: Callable[[], float]


def database_path(production_path):
    return os.path.abspath(os.getenv('DEMO_DB_PATH') or os.path.join(os.path.dirname(production_path),'demo','flux.db'))


def _file_identity(path):
    stat = os.stat(path)
    return stat.st_dev, stat.st_ino


def _inspect_database(path):
    """Prove ownership without opening an existing file for writing."""
    if not os.path.exists(path):
        return False, None
    identity = _file_identity(path)
    try:
        with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)) as c:
            objects = c.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            if not objects:
                owned = False
            else:
                tables = {name for name, kind in objects if kind == 'table'}
                marker = c.execute("SELECT v FROM settings WHERE k='isolated_demo_v1'").fetchall() if 'settings' in tables else []
                if marker != [('1',)]:
                    raise RuntimeError('O banco escolhido para demonstração já contém dados não identificados.')
                owned = True
    except sqlite3.DatabaseError as error:
        raise RuntimeError('O banco escolhido para demonstração não pôde ser identificado com segurança.') from error
    if _file_identity(path) != identity:
        raise RuntimeError('O banco da demonstração foi substituído durante a inspeção.')
    return owned, identity


def initialize(main: DemoRuntime):
    """Only a new empty database or an identified demo can receive schema writes."""
    path=database_path(main.production_database())
    production = os.path.abspath(main.production_database())
    same_file = os.path.exists(path) and os.path.exists(production) and os.path.samefile(path, production)
    if os.path.realpath(path) == os.path.realpath(production) or same_file:
        raise RuntimeError('O banco da demonstração deve ser separado do banco operacional.')
    with _lock:
        owned, identity = _inspect_database(path)
        # The ownership marker is checked even for a cached path. A replacement
        # file or an in-place removal of the marker must never bypass preflight.
        if owned and _initialized.get(path) == identity:
            return
        os.makedirs(os.path.dirname(path),exist_ok=True)
        with main.db() as c:
            if identity is not None and _file_identity(path) != identity:
                raise RuntimeError('O banco da demonstração foi substituído durante a inspeção.')
            if owned:
                marker = c.execute("SELECT v FROM settings WHERE k='isolated_demo_v1'").fetchone()
                if not marker or marker['v'] != '1':
                    raise RuntimeError('O banco escolhido para demonstração já contém dados não identificados.')
            elif c.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
                raise RuntimeError('O banco escolhido para demonstração já contém dados não identificados.')
            c.executescript(main.SCHEMA)
            c.execute('BEGIN IMMEDIATE')
            main.apply_sqlite_migrations(c,main.MIGRATIONS)
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_transaction_source ON transactions(source_key) WHERE source_key<>''")
            c.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_nsr ON time_entries(nsr) WHERE nsr IS NOT NULL')
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_admin_username ON admins(lower(username)) WHERE username<>''")
            if not owned:
                seed(main,c)
                c.execute("INSERT INTO settings(k,v) VALUES('isolated_demo_v1','1')")
            from app.employee_identity import link_legacy_references
            link_legacy_references(c)
        _initialized[path] = _file_identity(path)


def seed(main: DemoRuntime,c):
    from app import accounting,business
    now=main.local(main.utcnow());today=now.date();month=today.strftime('%Y-%m')
    settings={'co_name':'TechnoPlus · Empresa de demonstração','co_cnpj':'00000000000000','lat':'-23.5505','lng':'-46.6333','radius_m':'100',
              'daily_hours':'8','weekly_hours':'44','salary_hour_divisor':'220','overtime_multiplier':'1.5','setup_completed':'1',
              'vacation_rest_weekdays':'[6]','vacation_holidays':'[]','department_id_highwater':'3'}
    for key,value in settings.items():
        c.execute('INSERT INTO settings(k,v) VALUES(?,?)',(key,value))
    salt=secrets.token_hex(16)
    c.execute('INSERT INTO admins("user",username,salt,hash,role) VALUES(?,?,?,?,?)',
              ('demo@sigi.invalid','Demonstração',salt,main.hash_pin(secrets.token_urlsafe(32),salt),'admin'))
    for did,name in enumerate(('Produção','Administrativo','Comercial'),1):
        c.execute('INSERT INTO departments(id,name) VALUES(?,?)',(did,name))
    staff=[('Ana Lima','Supervisora de produção',6200,280,1),('Carlos Souza','Técnico industrial',4800,220,1),
           ('Beatriz Alves','Analista de RH',4100,180,2),('Rafael Costa','Consultor comercial',5300,320,3),
           ('Juliana Santos','Assistente comercial',3500,240,3),('Pedro Rocha','Técnico de manutenção',3900,200,1)]
    for eid,(name,role,salary,benefits,department) in enumerate(staff,1):
        pin_salt=secrets.token_hex(16)
        c.execute('INSERT INTO employees(id,name,role,salary,benefits,pin_salt,pin_hash,department_id,cpf) VALUES(?,?,?,?,?,?,?,?,?)',
                  (eid,name,role,salary,benefits,pin_salt,main.hash_pin(secrets.token_urlsafe(16),pin_salt),department,f'{eid:011d}'))
        c.execute('INSERT INTO employee_payroll_profiles(employee_id,hired_on,dependents,vt_amount,va_amount,va_discount,variable_average) VALUES(?,?,?,?,?,?,?)',
                  (eid,'2024-01-08',eid%3,220,550,55,100 if eid%2 else 0))
        c.execute('INSERT INTO employee_bonuses(employee_id,month,amount,note,updated_at,updated_by) VALUES(?,?,?,?,?,?)',
                  (eid,month,250 if eid%2 else 0,'Bonificação fictícia de produtividade',main.iso(main.utcnow()),'demo@sigi.invalid'))
    for did,eid in ((1,1),(2,3),(3,4)):
        c.execute('UPDATE departments SET lead_employee_id=? WHERE id=?',(eid,did))
    # Completed, hash-chained working days. No fake open clock blocks the demo.
    nsr=0;previous='0'*64
    for days_back in range(7,0,-1):
        day=today-timedelta(days=days_back)
        if day.weekday()>4:continue
        for eid in range(1,len(staff)+1):
            for kind,hour in [('entrada',8),('saida',12),('entrada',13),('saida',17)]:
                stamp=datetime(day.year,day.month,day.day,hour,tzinfo=timezone(timedelta(hours=-3))).astimezone(timezone.utc)
                nsr+=1;cpf=f'{eid:011d}';at=main.iso(stamp)
                digest=main.entry_hash(previous,nsr,cpf,at,eid,kind,-23.5505,-46.6333)
                c.execute('INSERT INTO time_entries(employee_id,kind,at,lat,lng,distance_m,accepted,reason,cpf,nsr,prev_hash,hash,samples,spread_m) VALUES(?,?,?,?,?,?,1,?,?,?,?,?,1,0)',
                          (eid,kind,at,-23.5505,-46.6333,0,'Registro fictício de demonstração',cpf,nsr,previous,digest))
                previous=digest
    titles=['Validar plano de manutenção','Conferir folha mensal','Preparar proposta comercial','Revisar estoque mínimo','Inspecionar painel elétrico','Atualizar cadastro de fornecedores']
    for tid,title in enumerate(titles,1):
        status=(tid-1)%3;department=(tid-1)%3+1
        c.execute('INSERT INTO tasks(id,title,assignee,due,status,priority,progress,approval,severity,department_id,labor_budget_hours,cost_ceiling) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                  (tid,title,staff[(tid-1)%len(staff)][0],str(today+timedelta(days=tid-2)),status,'alta' if tid%2 else 'media',100 if status==2 else 40,'aprovado' if status==2 else 'pendente','atencao' if tid==1 else 'normal',department,16,5000))
        for title2,done in [('Conferir informações',1),('Validar com responsável',int(status==2))]:
            c.execute('INSERT INTO task_checklist(task_id,title,done) VALUES(?,?,?)',(tid,title2,done))
        c.execute('INSERT INTO task_tags(task_id,tag) VALUES(?,?)',(tid,'Demonstração'))
    for name,unit,stock,cost,minimum in [('Aço inox','kg',420,68,100),('Parafusos','un',1250,1.8,200),('Tinta industrial','l',18,92,20),('Componentes elétricos','kit',24,145,10)]:
        c.execute('INSERT INTO materials(name,unit,stock,unit_cost,minimum_stock) VALUES(?,?,?,?,?)',(name,unit,stock,cost,minimum))
    for name,material,labor,overhead,price in [('Painel industrial',7800,4200,2100,18500),('Módulo de automação',5200,3400,1800,13800),('Manutenção preventiva',1200,2800,900,6200)]:
        c.execute('INSERT INTO products(name,material,labor,overhead,price) VALUES(?,?,?,?,?)',(name,material,labor,overhead,price))
    for i,(kind,description,amount,category,department,paid) in enumerate([
        ('receber','Projeto industrial · demonstração',18500,'revenue',None,1),('receber','Contrato de automação · demonstração',13800,'revenue',None,0),
        ('pagar','Compra de materiais · demonstração',4100,'cost',1,1),('pagar','Energia e manutenção · demonstração',1250,'operating',1,0),('pagar','Serviços administrativos · demonstração',2200,'operating',2,0)]):
        due=str(today+timedelta(days=i-1));paid_at=main.iso(main.utcnow()-timedelta(hours=1)) if paid else None
        tid=c.execute('INSERT INTO transactions(kind,description,amount,due,paid,paid_at,department_id,category,competence,source_key) VALUES(?,?,?,?,?,?,?,?,?,?) RETURNING id',
                      (kind,description,amount,due,paid,paid_at,department,category,month,'demo:finance:'+str(i))).fetchone()['id']
        transaction=dict(c.execute('SELECT * FROM transactions WHERE id=?',(tid,)).fetchone())
        accounting.sync_transaction(main.services,c,transaction,'demo@sigi.invalid')
        if paid:business.record_payment(main.services,c,transaction,'demo@sigi.invalid')
    for sid,(name,kind,capacity) in enumerate([('Sala de reuniões','gestao',8),('Bancada técnica','producao',12)],1):
        c.execute('INSERT INTO spaces(id,name,kind,capacity,admin_email,allow_shared) VALUES(?,?,?,?,?,1)',(sid,name,kind,capacity,'demo@sigi.invalid'))
    start=now.replace(hour=14,minute=0,second=0,microsecond=0)+timedelta(days=1)
    c.execute('INSERT INTO space_bookings(space_id,title,starts_at,ends_at,department_id,booked_by,attendees,exclusive,compatibility) VALUES(?,?,?,?,?,?,?,?,?)',
              (1,'Reunião de planejamento · demonstração',main.iso(start),main.iso(start+timedelta(hours=1)),2,'demo@sigi.invalid',5,1,''))
    c.execute('INSERT INTO vacation_records(employee_id,acquisition_start,days,starts_on,created_at,created_by) VALUES(?,?,?,?,?,?)',
              (1,'2024-01-08',14,'2025-02-03',main.iso(main.utcnow()),'demo@sigi.invalid'))
    for body in ['Bem-vindo à empresa de demonstração. Todos os registros são fictícios.','Revise o quadro de tarefas e os indicadores de RH para conhecer o sistema.']:
        c.execute("INSERT INTO messages(scope,sender_role,sender_name,body,created_at) VALUES('team','admin','Demonstração',?,?)",(body,main.iso(main.utcnow())))
    for title,revenue,material,opex,tax in [('Planejamento operacional',48000,14500,9800,7200),('Eficiência industrial',32000,7800,6400,4800)]:
        c.execute('INSERT INTO cost_analyses(title,revenue,material,opex,tax) VALUES(?,?,?,?,?)',(title,revenue,material,opex,tax))
    c.execute("INSERT INTO integrations(name,kind,endpoint,active) VALUES('Integração de exemplo','webhook','https://example.invalid/demo',0)")
    # Demonstrate one immutable, integrated closed payroll when a known tax table exists.
    previous_month=(today.replace(day=1)-timedelta(days=1)).strftime('%Y-%m')
    if previous_month.startswith('2026-'):
        data=business.payroll_data(main.services,previous_month,c)
        if data['employees']:
            rid=c.execute('INSERT INTO payroll_runs(month,closed_at,closed_by,rules_version) VALUES(?,?,?,?) RETURNING id',
                          (previous_month,main.iso(main.utcnow()),'demo@sigi.invalid',data['rules_version'])).fetchone()['id']
            due=str(today)
            for employee in data['employees']:
                c.execute('INSERT INTO payroll_items(run_id,employee_id,snapshot) VALUES(?,?,?)',(rid,employee['id'],json.dumps(employee)))
                c.execute("INSERT INTO transactions(kind,description,amount,due,department_id,category,competence,source_key) VALUES('pagar',?,?,?,?,?,?,?)",
                          ('Salário fictício · '+employee['name'],employee['net'],due,employee['department_id'],'personnel',previous_month,f"payroll:{rid}:{employee['id']}"))
            accounting.sync_payroll(main.services,c,rid,previous_month,'demo@sigi.invalid')
    accounting.event(main.services,c,{'role':'admin','user':'demo@sigi.invalid'},'demo_setup','isolated',{}, {'employees':len(staff)},'Dados fictícios de demonstração, sem envios externos')


class DatabaseScope:
    def __init__(self,app,main):self.app,self.main=app,main

    async def __call__(self,scope,receive,send):
        base_path=scope.get('root_path','').rstrip('/')
        path=route_path(scope,base_path)
        demo=path=='/demo' or path.startswith('/demo/')
        token=self.main.context.set(demo)
        base_token=self.main.base_path_context.set(base_path)
        try:
            if demo and scope['type'] in ('http','websocket'):
                await run_in_threadpool(initialize,self.main)
            await self.app(scope,receive,send)
        finally:
            self.main.context.reset(token)
            self.main.base_path_context.reset(base_token)


def route_path(scope,base_path=None):
    """Use the ASGI router's decoded path, relative to its deployment mount."""
    path=scope.get('path','')
    root=(scope.get('root_path','') if base_path is None else base_path).rstrip('/')
    if root and (path==root or path.startswith(root+'/')):
        return path[len(root):] or '/'
    return path


class ScopedStaticFiles(StaticFiles):
    """Bind frontend API routing to the same server-side realm as the request."""
    def __init__(self,*,directory,context,base_path_context,**kwargs):
        super().__init__(directory=directory,**kwargs)
        self.context=context
        self.base_path_context=base_path_context
        self.index_path=Path(directory,'index.html')

    async def get_response(self,path,scope):
        if self.html and path in ('.','index.html'):
            base=self.base_path_context.get()
            config=json.dumps({'basePath':base,'demo':bool(self.context.get())},ensure_ascii=True,separators=(',',':'))
            config=config.replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
            try:
                content=await run_in_threadpool(self.index_path.read_text)
            except FileNotFoundError:
                return await super().get_response(path,scope)
            if base:
                # Shared scripts, styles, icons and navigation stay under the mount.
                content=re.sub(r'((?:src|href)=[\"\'])/(?!/)',lambda match:match[1]+escape(base,quote=True)+'/',content)
            content=content.replace('<head>','<head><script>globalThis.SIGI_CONTEXT='+config+';</script>',1)
            return HTMLResponse(content,headers={'Cache-Control':'no-store'})
        return await super().get_response(path,scope)


def mount(main: DemoRuntime):
    from fastapi import HTTPException
    demo_app=FastAPI(title='SIGI · Demonstração')
    # Reuse route definitions, with a per-request, context-local database scope.
    demo_app.router.routes=list(main.app.router.routes)

    @demo_app.post('/auth/demo-login')
    def demo_login():
        if not main.context.get():raise HTTPException(404)
        token=secrets.token_urlsafe(32);now=main.timestamp()
        with main.db() as c:
            account=c.execute('SELECT "user" FROM admins WHERE "user"=?',('demo@sigi.invalid',)).fetchone()
            if not account:raise HTTPException(409,'A conta de demonstração foi alterada. Solicite a restauração da demonstração.')
            c.execute('DELETE FROM sessions WHERE expires<?',(now,))
            c.execute('INSERT INTO sessions(token,"user",expires,role) VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),account['user'],now+3600,'admin'))
        return {'token':token,'role':'admin','user':'demo@sigi.invalid','name':'Demonstração'}

    demo_app.mount('/',ScopedStaticFiles(directory=os.path.join(main.APP_DIR,'static'),html=True,context=main.context,base_path_context=main.base_path_context),name='demo-static')
    main.app.mount('/demo',demo_app,name='demo')
    main.app.add_middleware(DatabaseScope,main=main)
