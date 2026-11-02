"""Version and apply legacy SQLite column migrations without hiding failures."""
import hashlib
import re
import sqlite3
from collections.abc import Iterable


_ADD_COLUMN = re.compile(
    r'^ALTER\s+TABLE\s+([A-Za-z_][A-Za-z_0-9]*)\s+ADD\s+COLUMN\s+'
    r'([A-Za-z_][A-Za-z_0-9]*)\s+', re.IGNORECASE,
)


def apply_sqlite_migrations(connection: sqlite3.Connection, statements: Iterable[str]) -> None:
    """Use SQL content as stable version IDs, including already-present columns.

    The caller owns the transaction. Only a column proven present by SQLite's
    metadata is skipped; invalid SQL and all unexpected database errors propagate.
    """
    connection.execute('CREATE TABLE IF NOT EXISTS schema_migrations('
                       'version TEXT PRIMARY KEY, statement TEXT NOT NULL)')
    for statement in statements:
        version = hashlib.sha256(statement.encode('utf-8')).hexdigest()
        if connection.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
            continue
        match = _ADD_COLUMN.match(statement.strip())
        exists = False
        if match:
            table, column = match.groups()
            columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            exists = any(row[1].casefold() == column.casefold() for row in columns)
        if not exists:
            connection.execute(statement)
        connection.execute('INSERT INTO schema_migrations(version,statement) VALUES(?,?)',
                           (version, statement))
