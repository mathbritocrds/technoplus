import sqlite3

import pytest

from app.migrations import apply_sqlite_migrations


def test_legacy_existing_columns_are_recorded_and_new_columns_applied():
    with sqlite3.connect(':memory:') as connection:
        connection.execute('CREATE TABLE employees(id INTEGER PRIMARY KEY, name TEXT)')
        migrations = ['ALTER TABLE employees ADD COLUMN name TEXT',
                      'ALTER TABLE employees ADD COLUMN active INTEGER DEFAULT 1']
        apply_sqlite_migrations(connection, migrations)
        connection.execute("INSERT INTO employees(name) VALUES('Ana')")
        assert connection.execute('SELECT active FROM employees').fetchone() == (1,)
        assert connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone() == (2,)
        apply_sqlite_migrations(connection, migrations)
        assert connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone() == (2,)


@pytest.mark.parametrize('statement', [
    'ALTER TABLE missing ADD COLUMN active INTEGER',
    'ALTER TABLE employees ADD COLUMN age THIS IS INVALID SQL',
])
def test_unexpected_migration_errors_propagate_without_recording_success(statement):
    with sqlite3.connect(':memory:') as connection:
        connection.execute('CREATE TABLE employees(id INTEGER PRIMARY KEY)')
        with pytest.raises(sqlite3.OperationalError):
            apply_sqlite_migrations(connection, [statement])
        assert connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone() == (0,)


def test_failed_migration_transaction_can_roll_back_prior_changes():
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE employees(id INTEGER PRIMARY KEY)')
    with pytest.raises(sqlite3.OperationalError):
        with connection:
            connection.execute('BEGIN')
            apply_sqlite_migrations(connection, [
                'ALTER TABLE employees ADD COLUMN active INTEGER',
                'ALTER TABLE missing ADD COLUMN active INTEGER',
            ])
    assert [column[1] for column in connection.execute('PRAGMA table_info(employees)')] == ['id']
    connection.close()
