"""Credential limits cannot cross database realms, account types or origins."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.security import verify_totp
from app.security_limits import limited_attempts
from tests.test_security_regressions import otp

EMAIL='boundaries@example.test'
PASSWORD='boundaries-password'


@pytest.fixture
def account(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB',str(tmp_path/'prod.db'))
    monkeypatch.setenv('DEMO_DB_PATH',str(tmp_path/'demo.db'))
    monkeypatch.setattr(main,'SUPABASE_DATABASE_URL','')
    monkeypatch.setattr(main,'_fails',{})
    monkeypatch.setattr(main,'_pin_attempts',{})
    with main.db() as c:
        c.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(c,main.MIGRATIONS)
    with TestClient(main.app,client=('192.0.2.10',12345)) as client:
        response=client.post('/auth/register',json={'email':EMAIL,'username':'Boundary Admin','password':PASSWORD})
        assert response.status_code==201
        auth={'Authorization':'Bearer '+response.json()['token']}
        yield client,auth


def test_demo_login_failures_do_not_lock_production_management_login(account):
    client,_=account
    for _ in range(5):
        assert client.post('/demo/auth/login',json={'email':EMAIL,'password':'wrong'}).status_code==401
    assert client.post('/demo/auth/login',json={'email':EMAIL,'password':'wrong'}).status_code==429
    response=client.post('/auth/login',json={'email':EMAIL,'password':PASSWORD})
    assert response.status_code==200 and response.json()['token']


def test_demo_employee_failures_do_not_lock_real_employee(account):
    client,auth=account
    eid=client.post('/employees',headers=auth,json={'name':'Worker','salary':1000,'pin':'4321'}).json()['id']
    worker_email='worker-boundaries@example.test'
    assert client.post(f'/employees/{eid}/account',headers=auth,json={'email':worker_email,'password':PASSWORD}).status_code==201
    for _ in range(5):
        assert client.post('/demo/auth/employee/login',json={'email':worker_email,'password':'wrong'}).status_code==401
    response=client.post('/auth/employee/login',json={'email':worker_email,'password':PASSWORD})
    assert response.status_code==200 and response.json()['role']=='employee'


def test_management_and_employee_routes_keep_separate_identity_limits(account):
    client,_=account
    for _ in range(5):
        assert client.post('/auth/employee/login',json={'email':EMAIL,'password':'wrong'}).status_code==401
    assert client.post('/auth/login',json={'email':EMAIL,'password':PASSWORD}).status_code==200


def test_management_limits_are_origin_scoped_and_do_not_trust_forwarding_headers(account):
    client,_=account
    for _ in range(5):
        assert client.post('/auth/login',json={'email':EMAIL,'password':'wrong'}).status_code==401
    assert client.post('/auth/login',headers={'X-Forwarded-For':'192.0.2.11'},json={'email':EMAIL,'password':PASSWORD}).status_code==429
    with TestClient(main.app,client=('192.0.2.11',12345)) as other:
        assert other.post('/auth/login',json={'email':EMAIL,'password':PASSWORD}).status_code==200


def test_aggregate_auth_origin_limit_covers_distinct_identities(account):
    client,_=account
    for index in range(main.AUTH_ORIGIN_MAX_TRIES):
        assert client.post('/auth/login',json={'email':f'unknown-{index}@example.test','password':'wrong'}).status_code==401
    assert client.post('/auth/login',json={'email':EMAIL,'password':PASSWORD}).status_code==429


def test_demo_pin_failures_do_not_lock_production_pin(account):
    client,auth=account
    eid=client.post('/employees',headers=auth,json={'name':'Worker','salary':1000,'pin':'4321'}).json()['id']
    assert client.put('/settings/workplace',headers=auth,json={'lat':0,'lng':0,'radius_m':100}).status_code==200
    payload={'employee_id':eid,'pin':'0000','lat':0,'lng':0,'accuracy_m':10}
    for _ in range(5):
        assert client.post('/demo/clock/live',json=payload).status_code==401
    assert client.post('/clock/live',json={**payload,'pin':'4321'}).status_code==200


def test_unknown_pin_ids_count_towards_the_origin_limit(account):
    client,_=account
    for index in range(main.PIN_ORIGIN_MAX_TRIES):
        assert client.post('/clock/live',json={'employee_id':10000+index,'pin':'0000','lat':0,'lng':0}).status_code==404
    assert client.post('/clock/live',json={'employee_id':99999,'pin':'0000','lat':0,'lng':0}).status_code==423


def test_disable_requires_password_and_limits_totp_attempts_until_cooldown(account,monkeypatch):
    client,auth=account
    secret=client.post('/auth/2fa/setup',headers=auth).json()['secret']
    assert client.post('/auth/2fa/enable',headers=auth,json={'code':otp(secret)}).status_code==200
    assert client.post('/auth/2fa/disable',headers=auth,json={'code':otp(secret)}).status_code==422
    assert client.post('/auth/2fa/disable',headers=auth,json={'code':otp(secret),'current_password':'wrong'}).status_code==401
    wrong=next(f'{n:06d}' for n in range(100) if not verify_totp(secret,f'{n:06d}'))
    for _ in range(4):
        assert client.post('/auth/2fa/disable',headers=auth,json={'code':wrong,'current_password':PASSWORD}).status_code==400
    assert client.post('/auth/2fa/disable',headers=auth,json={'code':otp(secret),'current_password':PASSWORD}).status_code==429
    assert client.get('/auth/2fa',headers=auth).json()['enabled']
    now=time.monotonic()
    monkeypatch.setattr(main.time,'monotonic',lambda:now+301)
    assert client.post('/auth/2fa/disable',headers=auth,json={'code':otp(secret),'current_password':PASSWORD}).status_code==200


def test_active_setup_and_disable_share_protection_limit(account):
    client,auth=account
    secret=client.post('/auth/2fa/setup',headers=auth).json()['secret']
    assert client.post('/auth/2fa/enable',headers=auth,json={'code':otp(secret)}).status_code==200
    for _ in range(5):
        assert client.post('/auth/2fa/setup',headers=auth,json={'current_password':'wrong','code':'000000'}).status_code==401
    assert client.post('/auth/2fa/disable',headers=auth,json={'code':otp(secret),'current_password':PASSWORD}).status_code==429


def test_concurrent_checks_cannot_exceed_limit_and_expired_state_recovers():
    state={};lock=Lock();held=Barrier(6);release=Event();key=('realm','type','origin','identity')
    def attempt():
        try:
            with limited_attempts(state,lock,[(key,5)],100):
                held.wait(timeout=5)
                release.wait(timeout=5)
                raise HTTPException(401,'Wrong credential')
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures=[pool.submit(attempt) for _ in range(12)]
        try:
            held.wait(timeout=5)
        finally:
            release.set()
        statuses=[future.result() for future in futures]
    assert statuses.count(401)==5 and statuses.count(429)==7
    with limited_attempts(state,lock,[(key,5)],401):
        pass
    assert state=={}


def test_a_successful_concurrent_check_does_not_erase_failed_attempts():
    state={};lock=Lock();key=('realm','type','origin','identity')
    with limited_attempts(state,lock,[(key,5)],100):
        with pytest.raises(HTTPException):
            with limited_attempts(state,lock,[(key,5)],100):
                raise HTTPException(401,'Wrong credential')
    assert state[key][0]==1


def test_email_and_username_share_the_same_account_limit(account):
    client,_=account
    for _ in range(5):
        assert client.post('/auth/login',json={'email':EMAIL,'password':'wrong'}).status_code==401
    assert client.post('/auth/login',json={'user':'Boundary Admin','password':PASSWORD}).status_code==429
