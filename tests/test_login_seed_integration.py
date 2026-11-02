"""Remote UI changes must not introduce credentials or demo data into production."""
import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def installation(tmp_path,monkeypatch):
    path=str(tmp_path/'installation.db')
    monkeypatch.setattr(main,'DB',path)
    monkeypatch.setattr(main,'SUPABASE_DATABASE_URL','')
    with main.db() as c:
        c.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(c,main.MIGRATIONS)
        c.execute('INSERT INTO admins("user",username,role) VALUES(?,?,?)',('private@example.test','Private name','admin'))
    return path


def test_public_status_does_not_enumerate_admin_identity(installation):
    assert TestClient(main.app).get('/auth/status').json()=={'setup_required':False}


def test_restart_does_not_seed_accounts_data_or_gps_by_default(installation):
    environment={**os.environ,'DB_PATH':installation,'SUPABASE_DATABASE_URL':''}
    environment.pop('SIGI_DEMO_MODE',None)
    result=subprocess.run([sys.executable,'-c',
        'from app import main; import json\nwith main.db() as c:\n print(json.dumps([c.execute("SELECT COUNT(*) FROM employees").fetchone()[0],bool(c.execute("SELECT 1 FROM settings WHERE k=\'lat\'").fetchone())]))'],
        env=environment,capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)==[0,False]


def test_demo_seed_does_not_overwrite_operational_staff(installation):
    with main.db() as c:
        c.execute("INSERT INTO employees(name,salary,benefits) VALUES('Ana Lima',1234,12)")
    main.seed_operational_data()
    with main.db() as c:
        staff=c.execute('SELECT name,salary,benefits FROM employees').fetchall()
        assert len(staff)==1
        assert tuple(staff[0])==('Ana Lima',1234,12)
        assert c.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]==0
