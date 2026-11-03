"""Reject unknown demo files before any schema or data write."""
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def workspaces(tmp_path, monkeypatch):
    production = tmp_path / 'production.db'
    candidate = tmp_path / 'demo candidate #1.db'
    monkeypatch.setattr(main, 'DB', str(production))
    monkeypatch.setenv('DEMO_DB_PATH', str(candidate))
    monkeypatch.setattr(main, 'SUPABASE_DATABASE_URL', '')
    with main.db() as connection:
        connection.executescript(main.SCHEMA)
        main.apply_sqlite_migrations(connection, main.MIGRATIONS)
    return TestClient(main.app), candidate


def snapshot(path):
    with sqlite3.connect(path) as connection:
        return '\n'.join(connection.iterdump())


@pytest.mark.parametrize('schema', [
    'CREATE TABLE unrelated(id INTEGER PRIMARY KEY, details TEXT); '
    "INSERT INTO unrelated(details) VALUES('preserve this data');",
    'CREATE TABLE admins("user" TEXT PRIMARY KEY); '
    "INSERT INTO admins VALUES('existing@example.test');",
    'CREATE TABLE settings(k TEXT PRIMARY KEY,v TEXT); '
    "INSERT INTO settings VALUES('isolated_demo_v1','0');",
])
def test_unknown_database_is_rejected_without_altering_schema_or_records(workspaces, schema):
    client, candidate = workspaces
    with sqlite3.connect(candidate) as connection:
        connection.executescript(schema)
    before = snapshot(candidate)
    before_bytes = candidate.read_bytes()
    with pytest.raises(RuntimeError, match='dados não identificados'):
        client.post('/demo/auth/demo-login')
    assert snapshot(candidate) == before
    assert candidate.read_bytes() == before_bytes


def test_non_sqlite_file_is_rejected_without_alteration(workspaces):
    client, candidate = workspaces
    candidate.write_bytes(b'An unrelated file, not a SQLite database.')
    with pytest.raises(RuntimeError, match='identificado com segurança'):
        client.post('/demo/auth/demo-login')
    assert candidate.read_bytes() == b'An unrelated file, not a SQLite database.'


def test_empty_existing_database_can_be_initialized_repeatably(workspaces):
    client, candidate = workspaces
    candidate.touch()
    first = client.post('/demo/auth/demo-login')
    assert first.status_code == 200
    headers = {'Authorization': 'Bearer ' + first.json()['token']}
    assert len(client.get('/demo/employees', headers=headers).json()) == 6
    second = client.post('/demo/auth/demo-login')
    assert second.status_code == 200
    assert len(client.get('/demo/employees', headers=headers).json()) == 6


def test_replacement_file_cannot_bypass_initialized_path_cache(workspaces, tmp_path):
    client, candidate = workspaces
    assert client.post('/demo/auth/demo-login').status_code == 200
    replacement = tmp_path / 'replacement.db'
    with sqlite3.connect(replacement) as connection:
        connection.execute('CREATE TABLE unrelated(details TEXT)')
        connection.execute("INSERT INTO unrelated VALUES('do not migrate')")
    os.replace(replacement, candidate)
    before = snapshot(candidate)
    before_bytes = candidate.read_bytes()
    with pytest.raises(RuntimeError, match='dados não identificados'):
        client.post('/demo/auth/demo-login')
    assert snapshot(candidate) == before
    assert candidate.read_bytes() == before_bytes


def test_missing_marker_is_rechecked_even_if_file_identity_is_cached(workspaces):
    client, candidate = workspaces
    assert client.post('/demo/auth/demo-login').status_code == 200
    with sqlite3.connect(candidate) as connection:
        connection.execute("DELETE FROM settings WHERE k='isolated_demo_v1'")
    before = snapshot(candidate)
    with pytest.raises(RuntimeError, match='dados não identificados'):
        client.post('/demo/auth/demo-login')
    assert snapshot(candidate) == before
