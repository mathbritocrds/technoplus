"""Portable schema for append-only payroll adjustments and administrative controls."""
SCHEMA = '''
CREATE TABLE IF NOT EXISTS payroll_adjustments(
 id INTEGER PRIMARY KEY, month TEXT NOT NULL, reference TEXT NOT NULL UNIQUE,
 reason TEXT NOT NULL, booked_on TEXT NOT NULL, created_at TEXT NOT NULL,
 created_by TEXT NOT NULL, current_json TEXT NOT NULL, delta_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_payroll_adjustments_month ON payroll_adjustments(month,id);
CREATE TABLE IF NOT EXISTS accounting_periods(
 month TEXT PRIMARY KEY, closed INTEGER NOT NULL DEFAULT 1,
 closed_at TEXT NOT NULL, closed_by TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bank_entries(
 id INTEGER PRIMARY KEY, account TEXT NOT NULL, reference TEXT NOT NULL,
 booked_on TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents<>0),
 description TEXT NOT NULL, imported_at TEXT NOT NULL, imported_by TEXT NOT NULL,
 UNIQUE(account,reference));
CREATE TABLE IF NOT EXISTS bank_matches(
 id INTEGER PRIMARY KEY, bank_entry_id INTEGER NOT NULL UNIQUE REFERENCES bank_entries(id),
 payment_id INTEGER NOT NULL UNIQUE REFERENCES payment_history(id),
 reason TEXT NOT NULL, matched_at TEXT NOT NULL, matched_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS compliance_records(
 id INTEGER PRIMARY KEY, month TEXT NOT NULL, kind TEXT NOT NULL,
 reference TEXT NOT NULL UNIQUE, evidence TEXT NOT NULL, reason TEXT NOT NULL,
 created_at TEXT NOT NULL, created_by TEXT NOT NULL);
'''
IMMUTABLE_TABLES = ('payroll_adjustments', 'bank_entries', 'bank_matches', 'compliance_records')
SQLITE_GUARDS = '\n'.join(
 f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} "
 "BEGIN SELECT RAISE(ABORT,'Registro administrativo imutável.'); END;"
 for table in IMMUTABLE_TABLES for action in ('UPDATE', 'DELETE'))

SQLITE_GUARDS += """
CREATE TRIGGER IF NOT EXISTS ledger_period_guard BEFORE INSERT ON ledger_journals
WHEN EXISTS(SELECT 1 FROM accounting_periods WHERE month=substr(NEW.booked_on,1,7) AND closed=1)
BEGIN SELECT RAISE(ABORT,'Competência contábil encerrada.'); END;
"""

SQLITE_GUARDS += """
CREATE TRIGGER IF NOT EXISTS ledger_period_update_guard BEFORE UPDATE OF booked_on,status ON ledger_journals
WHEN EXISTS(SELECT 1 FROM accounting_periods WHERE month=substr(NEW.booked_on,1,7) AND closed=1)
BEGIN SELECT RAISE(ABORT,'Competência contábil encerrada.'); END;
"""
