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


def department_lead(connection, employee_id=None, name='', department_id=None):
    """One rule for explicit department changes and safe legacy recovery."""
    if employee_id is None and name.strip():
        matches=connection.execute('SELECT id FROM employees WHERE active=1 AND lower(name)=lower(?)',(name.strip(),)).fetchall()
        if len(matches)!=1:
            raise HTTPException(400,'Selecione um funcionário ativo cadastrado como chefe do departamento.')
        employee_id=matches[0]['id']
    if employee_id is None:
        return None,''
    person=connection.execute('SELECT id,name,department_id FROM employees WHERE id=? AND active=1',(employee_id,)).fetchone()
    if not person:
        raise HTTPException(400,'Chefe deve ser um funcionário ativo cadastrado.')
    if person['department_id'] is not None and person['department_id']!=department_id:
        raise HTTPException(400,'O chefe já pertence a outro departamento. Transfira-o antes.')
    others=connection.execute('SELECT id FROM departments WHERE lead_employee_id=?',(employee_id,)).fetchall()
    if any(row['id']!=department_id for row in others):
        raise HTTPException(400,'Este funcionário já é chefe de outro departamento.')
    return employee_id,person['name']


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
    for employee in connection.execute('SELECT id FROM employees WHERE active=1 AND department_id IS NULL').fetchall():
        linked=connection.execute('SELECT id FROM departments WHERE lead_employee_id=?',(employee['id'],)).fetchall()
        if len(linked)==1:
            department_lead(connection,employee['id'],department_id=linked[0]['id'])
            connection.execute('UPDATE employees SET department_id=? WHERE id=?',(linked[0]['id'],employee['id']))
    people,aliases=_directory(connection)
    for task in connection.execute("SELECT id,assignee,department_id FROM tasks WHERE assignee_employee_id IS NULL AND assignee_external=0 AND assignee<>''").fetchall():
        person=_match(people,aliases,task['assignee'],task['department_id'])
        if person:
            connection.execute('UPDATE tasks SET assignee_employee_id=?,assignee=? WHERE id=?',
                               (person['id'],person['name'],task['id']))
    # Resolve all candidates before writing: two legacy sectors must not claim
    # the same employee merely because the first update changed the directory.
    proposals=defaultdict(list)
    for department in connection.execute("SELECT id,lead FROM departments WHERE lead_employee_id IS NULL AND lead<>''").fetchall():
        person=_match(people,aliases,department['lead'],department['id'])
        if person and person['active'] and person['department_id'] in (None,department['id']):
            proposals[person['id']].append(department['id'])
    for eid,departments in proposals.items():
        if len(departments)!=1 or connection.execute(
                'SELECT 1 FROM departments WHERE lead_employee_id=?',(eid,)).fetchone():
            continue
        did=departments[0]
        _,name=department_lead(connection,eid,department_id=did)
        connection.execute('UPDATE departments SET lead_employee_id=?,lead=? WHERE id=?',
                           (eid,name,did))
        connection.execute('UPDATE employees SET department_id=? WHERE id=?',(did,eid))


def assignment(connection, name='', employee_id=None, department_id=None, *, external=False):
    if external and employee_id is None:
        return name.strip(),None
    if employee_id is not None:
        person=connection.execute('SELECT id,name,active FROM employees WHERE id=?',(employee_id,)).fetchone()
        if not person or not person['active']:
            raise HTTPException(404,'Funcionário responsável não encontrado ou inativo.')
        return person['name'],person['id']
    if not _key(name):
        return '',None
    people,aliases=_directory(connection)
    # Current names take precedence over aliases, but ambiguity requires an ID.
    current=defaultdict(set)
    for eid,employee in people.items():
        current[_key(employee['name'])].add(eid)
    candidates=current if current.get(_key(name)) else aliases
    person=_match(people,candidates,name,department_id)
    if person:
        if not person['active']:
            raise HTTPException(404,'Funcionário responsável não encontrado ou inativo.')
        return person['name'],person['id']
    if candidates.get(_key(name)):
        raise HTTPException(409,'Há funcionários com esse nome. Selecione o responsável pelo cadastro.')
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
