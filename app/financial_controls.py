"""Common period guard used by manual and automatic journal posting."""
from fastapi import HTTPException


def ensure_open(connection, booked_on):
    # Serialize posting against close/reopen using the same transaction lock.
    if hasattr(connection, 'connection') or not connection.in_transaction:
        connection.execute('BEGIN IMMEDIATE')
    month = str(booked_on)[:7]
    row = connection.execute('SELECT closed FROM accounting_periods WHERE month=?', (month,)).fetchone()
    if row and row['closed']:
        raise HTTPException(409, 'Competência contábil encerrada. Reabra com justificativa ou lance ajuste em período aberto.')
