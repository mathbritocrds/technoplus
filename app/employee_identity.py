"""Stable employee references and current display names without rewriting history."""
import json
import re
from collections import defaultdict

from fastapi import HTTPException


def _key(value):
    return (value or '').strip().casefold()


def _remember(connection, employee_id, name):
    if isinstance(name,str) and name.strip():
        connection.execute('INSERT INTO employee_name_aliases(employee_id,name) VALUES(?,?) ON CONFLICT(employee_id,name) DO NOTHING',
                           (employee_id, name.strip()))


def _directory(connection):
    people={row['id']:dict(row) for row in connection.execute('SELECT id,name,department_id,active FROM employees')}
    aliases=defaultdict(set)
    for eid,employee in people.items():
        aliases[_key(employee['name'])].add(eid)
    for row in connection.execute('SELECT employee_id,name FROM employee_name_aliases'):
        if row['employee_id'] in people:
            aliases[_key(row['name'])].add(row['employee_id'])
    return people,aliases


def _match(people, aliases, name, department_id=None):
    candidates=aliases.get(_key(name),set())
    if len(candidates)==1:
        return people[next(iter(candidates))]
    if department_id is not None:
        candidates={eid for eid in candidates if people[eid]['department_id']==department_id}
        if len(candidates)==1:
            return people[next(iter(candidates))]
    return None


def link_legacy_references(connection):
    """Recover unambiguous links, including names retained in immutable snapshots."""
    if not connection.execute("SELECT 1 FROM settings WHERE k='employee_identity_v1'").fetchone():
        people={row['id'] for row in connection.execute('SELECT id FROM employees')}
        for query,column,multiple in [
            ('SELECT snapshot FROM payroll_items','snapshot',False),
            ('SELECT current_json FROM payroll_adjustments','current_json',True),
        ]:
            for row in connection.execute(query):
                try:
                    saved=json.loads(row[column]);records=saved if multiple else [saved]
                    for person in records:
                        if isinstance(person,dict) and person.get('id') in people:
                            _remember(connection,person['id'],person.get('name'))
                except (ValueError,TypeError):
                    continue
        for row in connection.execute('SELECT sender_employee_id,sender_name FROM messages WHERE sender_role=\'employee\' AND sender_employee_id IS NOT NULL'):
            if row['sender_employee_id'] in people:
                _remember(connection,row['sender_employee_id'],row['sender_name'])
        for row in connection.execute('SELECT lead_employee_id,lead FROM departments WHERE lead_employee_id IS NOT NULL'):
            if row['lead_employee_id'] in people:
                _remember(connection,row['lead_employee_id'],row['lead'])
        connection.execute("INSERT INTO settings(k,v) VALUES('employee_identity_v1','1') ON CONFLICT(k) DO NOTHING")
    people,aliases=_directory(connection)
    for task in connection.execute("SELECT id,assignee,department_id FROM tasks WHERE assignee_employee_id IS NULL AND assignee<>''").fetchall():
        person=_match(people,aliases,task['assignee'],task['department_id'])
        if person:
            connection.execute('UPDATE tasks SET assignee_employee_id=?,assignee=? WHERE id=?',
                               (person['id'],person['name'],task['id']))
    for department in connection.execute("SELECT id,lead FROM departments WHERE lead_employee_id IS NULL AND lead<>''").fetchall():
        person=_match(people,aliases,department['lead'],department['id'])
        if person and person['department_id'] in (None,department['id']):
            connection.execute('UPDATE departments SET lead_employee_id=?,lead=? WHERE id=?',
                               (person['id'],person['name'],department['id']))


def assignment(connection, name='', employee_id=None, department_id=None):
    if employee_id is not None:
        person=connection.execute('SELECT id,name,active FROM employees WHERE id=?',(employee_id,)).fetchone()
        if not person or not person['active']:
            raise HTTPException(404,'Funcionário responsável não encontrado ou inativo.')
        return person['name'],person['id']
    if not _key(name):
        return '',None
    people,aliases=_directory(connection)
    # An explicit current name takes precedence over a former employee alias.
    current=defaultdict(set)
    for eid,employee in people.items():
        current[_key(employee['name'])].add(eid)
    person=_match(people,current,name,department_id) or _match(people,aliases,name,department_id)
    if person:
        return person['name'],person['id']
    return name.strip(),None


def rename_employee(connection, employee_id, previous, current):
    _remember(connection,employee_id,previous)
    link_legacy_references(connection)
    connection.execute('UPDATE tasks SET assignee=? WHERE assignee_employee_id=?',(current,employee_id))
    connection.execute('UPDATE departments SET lead=? WHERE lead_employee_id=?',(current,employee_id))


def current_payroll_descriptions(connection, items):
    """Operational display follows the employee; stored receipts remain untouched."""
    names={row['id']:row['name'] for row in connection.execute('SELECT id,name FROM employees')}
    for item in items:
        match=re.fullmatch(r'payroll:(?:\d+|adjustment:\d+):(\d+)',item.get('source_key',''))
        if not match or int(match[1]) not in names:
            continue
        prefix,separator,_=item['description'].partition(' · ')
        if separator:
            description=prefix+separator+names[int(match[1])]
            if description!=item['description']:
                item['recorded_description']=item['description']
                item['description']=description
    return items
