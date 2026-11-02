"""Regression checks for account protection and origin-scoped PIN throttling."""
import base64
import hashlib
import hmac
import sqlite3
import struct
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.security import verify_totp


PASSWORD = 'regression-password'
EMAIL = 'security@example.test'


def otp(secret):
    key = base64.b32decode(secret + '=' * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack('>Q', int(time.time() // 30)), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f'{(struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000:06d}'


@pytest.fixture
def account(tmp_path, monkeypatch):
    database = str(tmp_path / 'security.db')
    with sqlite3.connect(database) as connection:
        connection.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(connection, main.MIGRATIONS)
    monkeypatch.setattr(main, 'DB', database)
    monkeypatch.setattr(main, 'SUPABASE_DATABASE_URL', '')
    monkeypatch.setattr(main, '_pin_attempts', {})
    monkeypatch.setattr(main, '_fails', {})
    with TestClient(main.app, client=('192.0.2.1', 12345)) as client:
        response = client.post('/auth/register', json={
            'email': EMAIL, 'username': 'Security', 'password': PASSWORD,
        })
        assert response.status_code == 201
        headers = {'Authorization': 'Bearer ' + response.json()['token']}
        yield client, headers


def enable(client, headers):
    setup = client.post('/auth/2fa/setup', headers=headers)
    assert setup.status_code == 200
    secret = setup.json()['secret']
    assert client.post('/auth/2fa/enable', headers=headers, json={'code': otp(secret)}).status_code == 200
    return secret


def test_active_totp_cannot_be_reset_by_session_alone(account):
    client, headers = account
    original = enable(client, headers)
    assert client.post('/auth/2fa/setup', headers=headers).status_code == 401
    assert client.post('/auth/2fa/setup', headers=headers, json={
        'current_password': 'wrong', 'code': otp(original),
    }).status_code == 401
    assert client.get('/auth/2fa', headers=headers).json() == {'enabled': True}
    assert client.post('/auth/login', json={'email': EMAIL, 'password': PASSWORD}).json() == {'requires_otp': True}


def test_totp_rotation_preserves_old_secret_until_confirmation(account):
    client, headers = account
    original = enable(client, headers)
    replacement = client.post('/auth/2fa/setup', headers=headers, json={
        'current_password': PASSWORD, 'code': otp(original),
    }).json()['secret']
    with main.db() as connection:
        row = connection.execute('SELECT totp_secret,totp_enabled FROM admins').fetchone()
        assert row['totp_secret'] == original and row['totp_enabled'] == 1
    invalid = next(f'{n:06d}' for n in range(100) if not verify_totp(replacement, f'{n:06d}'))
    assert client.post('/auth/2fa/enable', headers=headers, json={'code': invalid}).status_code == 400
    assert client.post('/auth/2fa/enable', headers=headers, json={'code': otp(replacement)}).status_code == 200
    with main.db() as connection:
        assert connection.execute('SELECT totp_secret FROM admins').fetchone()['totp_secret'] == replacement


def test_password_change_revokes_other_sessions_but_preserves_current(account):
    client, headers = account
    other = client.post('/auth/login', json={'email': EMAIL, 'password': PASSWORD}).json()['token']
    response = client.put('/auth/account', headers=headers, json={
        'email': EMAIL, 'username': 'Security', 'current_password': PASSWORD,
        'new_password': 'replacement-password',
    })
    assert response.status_code == 200
    assert client.get('/auth/account', headers=headers).status_code == 200
    assert client.get('/auth/account', headers={'Authorization': 'Bearer ' + other}).status_code == 401
    assert client.post('/auth/login', json={'email': EMAIL, 'password': PASSWORD}).status_code == 401
    assert client.post('/auth/login', json={'email': EMAIL, 'password': 'replacement-password'}).status_code == 200


def test_pin_lockout_is_temporary_and_does_not_block_other_origins(account, monkeypatch):
    client, headers = account
    employee = client.post('/employees', headers=headers, json={
        'name': 'Worker', 'salary': 1000, 'pin': '1234',
    }).json()['id']
    payload = {'employee_id': employee, 'pin': '0000', 'lat': 0, 'lng': 0}
    assert [client.post('/clock/live', json=payload).status_code for _ in range(5)] == [401] * 5
    payload['pin'] = '1234'
    assert client.post('/clock/live', json=payload).status_code == 423
    with TestClient(main.app, client=('192.0.2.2', 12345)) as other:
        # Authentication succeeded; the unconfigured workplace is the next check.
        assert other.post('/clock/live', json=payload).status_code == 409
    now = time.monotonic()
    monkeypatch.setattr(main.time, 'monotonic', lambda: now + main.PIN_COOLDOWN_SECONDS + 1)
    assert client.post('/clock/live', json=payload).status_code == 409


def test_pin_origin_limit_also_covers_attempts_across_employee_ids(account):
    client, headers = account
    ids = [client.post('/employees', headers=headers, json={
        'name': f'Worker {n}', 'salary': 1000, 'pin': '1234',
    }).json()['id'] for n in range(6)]
    for index in range(main.PIN_ORIGIN_MAX_TRIES):
        response = client.post('/clock/live', json={
            'employee_id': ids[index % 5], 'pin': '0000', 'lat': 0, 'lng': 0,
        })
        assert response.status_code == 401
    assert client.post('/clock/live', json={
        'employee_id': ids[-1], 'pin': '1234', 'lat': 0, 'lng': 0,
    }).status_code == 423


def test_pending_totp_expires_without_changing_active_protection(account):
    import json

    client, headers = account
    original = enable(client, headers)
    replacement = client.post('/auth/2fa/setup', headers=headers, json={
        'current_password': PASSWORD, 'code': otp(original),
    }).json()['secret']
    with main.db() as connection:
        key = main.pending_totp_key(EMAIL)
        row = connection.execute('SELECT v FROM settings WHERE k=?', (key,)).fetchone()
        pending = json.loads(row['v'])
        pending['expires'] = time.time() - 1
        connection.execute('UPDATE settings SET v=? WHERE k=?', (json.dumps(pending), key))
    assert client.post('/auth/2fa/enable', headers=headers, json={'code': otp(replacement)}).status_code == 400
    with main.db() as connection:
        row = connection.execute('SELECT totp_secret,totp_enabled FROM admins').fetchone()
        assert row['totp_secret'] == original and row['totp_enabled'] == 1


def test_pending_totp_has_finite_confirmation_attempts(account):
    client, headers = account
    pending = client.post('/auth/2fa/setup', headers=headers).json()['secret']
    invalid = next(f'{n:06d}' for n in range(100) if not verify_totp(pending, f'{n:06d}'))
    for _ in range(5):
        assert client.post('/auth/2fa/enable', headers=headers, json={'code': invalid}).status_code == 400
    response = client.post('/auth/2fa/enable', headers=headers, json={'code': otp(pending)})
    assert response.status_code == 400
    assert client.get('/auth/2fa', headers=headers).json() == {'enabled': False}
