"""Cross-boundary clock pairing and one shared overtime calculation."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import main
from app.timekeeping import summarize

TZ = timezone(timedelta(hours=-3))


def stamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def entry(index, kind, value):
    return {'id': index, 'employee_id': 1, 'kind': kind, 'at': stamp(value).isoformat()}


def test_shift_is_split_at_local_midnight_and_month_year_boundary():
    records = [entry(1, 'entrada', '2026-12-31T22:00'), entry(2, 'saida', '2027-01-01T06:00')]
    december = summarize(records, stamp('2026-12-01T00:00'), stamp('2027-01-01T00:00'), TZ)[1]
    january = summarize(records, stamp('2027-01-01T00:00'), stamp('2027-02-01T00:00'), TZ)[1]
    assert december['total'] == 2 and january['total'] == 6
    assert not december['open'] and not january['open']


def test_weekly_overtime_is_not_added_twice_to_daily_overtime():
    records = []
    for day in range(5, 11):
        records.extend([entry(day*2, 'entrada', f'2026-01-{day:02}T08:00'), entry(day*2+1, 'saida', f'2026-01-{day:02}T16:00')])
    result = summarize(records, stamp('2026-01-01T00:00'), stamp('2026-02-01T00:00'), TZ)[1]
    assert result['total'] == 48 and result['overtime'] == 4
    result = summarize(records, stamp('2026-01-01T00:00'), stamp('2026-02-01T00:00'), TZ, daily_hours=6, weekly_hours=30)[1]
    assert result['overtime'] == 18


def test_weekly_normal_hours_include_previous_competence():
    records=[]
    for index, day in enumerate(['2026-04-27','2026-04-28','2026-04-29','2026-04-30','2026-05-01','2026-05-02']):
        records.extend([entry(index*2, 'entrada', day+'T08:00'), entry(index*2+1,'saida',day+'T16:00')])
    may=summarize(records,stamp('2026-05-01T00:00'),stamp('2026-06-01T00:00'),TZ)[1]
    assert may['total']==16 and may['overtime']==4


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(main,'DB',str(tmp_path/'clock.db'))
    monkeypatch.setattr(main,'SUPABASE_DATABASE_URL','')
    monkeypatch.setattr(main,'_pin_attempts',{})
    with main.db() as c:
        c.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(c,main.MIGRATIONS)
    client=TestClient(main.app)
    response=client.post('/auth/register',json={'email':'clock@test.com','password':'clock-test-password'})
    assert response.status_code==201
    auth={'Authorization':'Bearer '+response.json()['token']}
    eid=client.post('/employees',headers=auth,json={'name':'Noite','salary':2200,'pin':'1234','hired_on':'2026-01-01'}).json()['id']
    assert client.put('/settings/workplace',headers=auth,json={'lat':0,'lng':0,'radius_m':100}).status_code==200
    return client,auth,eid


def test_clock_api_alternates_across_days_and_preserves_task(service,monkeypatch):
    client,auth,eid=service
    task=client.post('/tasks',headers=auth,json={'title':'Plantão','status':1}).json()['id']
    payload={'employee_id':eid,'pin':'1234','consent':True,'task_id':task,'samples':[{'lat':0,'lng':0,'accuracy_m':10}]}
    monkeypatch.setattr(main,'utcnow',lambda: stamp('2026-10-31T19:00').astimezone(timezone.utc))
    assert client.post('/clock',json=payload).json()['kind']=='entrada'
    monkeypatch.setattr(main,'utcnow',lambda: stamp('2026-11-01T05:00').astimezone(timezone.utc))
    payload.pop('task_id')
    response=client.post('/clock',json=payload)
    assert response.status_code==200 and response.json()['kind']=='saida'
    with main.db() as c:
        assert [row['task_id'] for row in c.execute('SELECT task_id FROM time_entries ORDER BY id')]==[task,task]
    october=client.get('/timesheet?month=2026-10',headers=auth).json()['employees'][0]
    november=client.get('/timesheet?month=2026-11',headers=auth).json()['employees'][0]
    assert october['total_hours']==5 and november['total_hours']==5
    assert october['overtime_hours']==0 and november['overtime_hours']==2
    assert not october['open'] and not november['open']
    assert client.get('/time-entries/verify',headers=auth).json()['ok']


def test_live_dashboard_portal_and_operations_share_six_hour_target(service,monkeypatch):
    client,auth,eid=service
    now=stamp('2026-11-02T15:00').astimezone(timezone.utc)
    monkeypatch.setattr(main,'utcnow',lambda:now)
    with main.db() as c:
        c.execute("INSERT INTO settings(k,v) VALUES('daily_hours','6') ON CONFLICT(k) DO UPDATE SET v='6'")
        c.execute('INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,?,?,1)',(eid,'entrada',(now-timedelta(hours=7)).isoformat()))
    portal=main.employee_summary({'employee_id':eid})
    panel=client.get('/dashboard',headers=auth).json()
    operations=client.get('/admin/operations?month=2026-11',headers=auth).json()
    assert portal['worked_minutes']==420 and portal['bank_minutes']==60
    assert panel['hours_worked']==7 and panel['overtime_hours']==1 and panel['overtime_threshold_hours']==6
    assert sum(row['overtime_hours'] for row in operations['departments'])==1


def test_operations_uses_corrected_entries(service,monkeypatch):
    client,auth,eid=service
    now=stamp('2026-11-02T20:00').astimezone(timezone.utc)
    monkeypatch.setattr(main,'utcnow',lambda:now)
    with main.db() as c:
        c.execute('INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,?,?,1)',(eid,'entrada',stamp('2026-11-02T08:00').isoformat()))
        end=c.execute('INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,?,?,1) RETURNING id',(eid,'saida',stamp('2026-11-02T16:00').isoformat())).fetchone()['id']
        c.execute('INSERT INTO time_entry_adjustments(entry_id,corrected_at,reason,created_at,created_by,department_id) VALUES(?,?,?,?,?,NULL)',(end,stamp('2026-11-02T18:00').isoformat(),'Correção conferida',now.isoformat(),'clock@test.com'))
    operations=client.get('/admin/operations?month=2026-11',headers=auth).json()
    assert sum(row['overtime_hours'] for row in operations['departments'])==2


def test_employee_day_counter_clips_overnight_open_shift(service,monkeypatch):
    client,auth,eid=service
    now=stamp('2026-11-02T05:00').astimezone(timezone.utc)
    monkeypatch.setattr(main,'utcnow',lambda:now)
    with main.db() as c:
        c.execute('INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,?,?,1)',(eid,'entrada',stamp('2026-11-01T19:00').isoformat()))
    summary=main.employee_summary({'employee_id':eid})
    assert summary['worked_minutes']==300 and summary['on_clock']
    assert datetime.fromisoformat(summary['counter_started_at']).astimezone(TZ)==stamp('2026-11-02T00:00')
    assert datetime.fromisoformat(summary['clocked_since']).astimezone(TZ)==stamp('2026-11-01T19:00')


def test_overnight_shift_preserves_daily_allowance_after_midnight():
    rows=[entry(1,'entrada','2026-10-31T19:00'),entry(2,'saida','2026-11-01T05:00')]
    october=summarize(rows,stamp('2026-10-01T00:00'),stamp('2026-11-01T00:00'),TZ)[1]
    november=summarize(rows,stamp('2026-11-01T00:00'),stamp('2026-12-01T00:00'),TZ)[1]
    assert october['total']==5 and october['overtime']==0
    assert november['total']==5 and november['overtime']==2


def test_multiple_pairs_starting_same_workday_share_daily_allowance():
    rows=[entry(1,'entrada','2026-10-31T10:00'),entry(2,'saida','2026-10-31T14:00'),
          entry(3,'entrada','2026-10-31T19:00'),entry(4,'saida','2026-11-01T01:00')]
    november=summarize(rows,stamp('2026-11-01T00:00'),stamp('2026-12-01T00:00'),TZ)[1]
    october=summarize(rows,stamp('2026-10-01T00:00'),stamp('2026-11-01T00:00'),TZ)[1]
    assert october['total']==9 and october['overtime']==1
    assert november['total']==1 and november['overtime']==1
