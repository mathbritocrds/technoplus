// Run the actual Python attendance query in a PostgreSQL engine.
import {spawnSync} from 'node:child_process';
import {PGlite} from '@electric-sql/pglite';
import assert from 'node:assert/strict';
const captured=spawnSync('.venv/bin/python',['-c',`
import json
from datetime import timezone
from app.database import PostgresConnection
from app.timekeeping import payroll_months
class Capture(PostgresConnection):
 def __init__(self): pass
 def execute(self,sql,params):
  print(json.dumps({'sql':sql,'params':params}))
  return []
payroll_months(Capture(),['2026-02'],{},timezone.utc,employee_id=1)
`],{encoding:'utf8'});
assert.equal(captured.status,0,captured.stderr);
const query=JSON.parse(captured.stdout);
let index=0;const sql=query.sql.replaceAll('?',()=>`$${++index}`);
const pg=new PGlite();
try {
 await pg.exec(`CREATE TABLE effective_time_entries(id INTEGER,employee_id INTEGER,kind TEXT,effective_at TEXT,accepted INTEGER);
 INSERT INTO effective_time_entries VALUES
 (1,1,'entrada','2024-01-01T09:00:00+00:00',1),(2,1,'saida','2024-01-01T17:00:00+00:00',1),
 (3,1,'entrada','2026-02-28T22:00:00+00:00',1),(4,1,'saida','2026-03-01T06:00:00+00:00',1),
 (5,2,'entrada','2026-02-01T09:00:00+00:00',1),(6,1,'entrada','2026-02-01T09:00:00+00:00',0);`);
 assert.deepEqual((await pg.query(sql,query.params)).rows.map(row=>row.id),[3,4]);
 console.log('PostgreSQL: bounded payroll attendance, employee scope, accepted records, month-end carry verified.');
} finally {await pg.close();}
