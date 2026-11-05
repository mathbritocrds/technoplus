"""Pair accepted clock records globally before allocating local days and overtime."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta


def summarize(entries, start, end, tz, daily_hours=8, weekly_hours=44, now=None, contracts=None):
    """Return completed hours (plus live hours when now is supplied).

    Daily and Monday–Sunday weekly thresholds share the same normal hours,
    attributed to the local entry day even when a shift crosses midnight:
    an hour classified as daily overtime never consumes the weekly allowance.
    Pairing includes records outside the requested period, including the part
    of the week in the previous month. Pending records remain explicit.
    """
    grouped = defaultdict(list)
    for entry in entries:
        row = dict(entry)
        row['stamp'] = datetime.fromisoformat(row.get('effective_at', row['at']))
        grouped[row['employee_id']].append(row)
    result = {}
    for employee_id, records in grouped.items():
        records.sort(key=lambda row: (row['stamp'], row['id']))
        days = defaultdict(float)
        daily_normal = defaultdict(float)
        weekly_normal = defaultdict(float)
        extra_by_day = defaultdict(float)
        contract=(contracts or {}).get(employee_id,{})
        contract_start=datetime.combine(date.fromisoformat(contract['hired_on']),time.min,tzinfo=tz) if contract.get('hired_on') else None
        contract_end=datetime.combine(date.fromisoformat(contract['terminated_on'])+timedelta(days=1),time.min,tzinfo=tz) if contract.get('terminated_on') else None
        opened = None
        anomalies = []
        pending = []

        def allocate(left, right):
            # Contract bounds apply before daily/weekly allowances are consumed.
            if contract_start: left=max(left,contract_start)
            if contract_end: right=min(right,contract_end)
            right=min(right,end)
            if left>=right: return
            # A continuous shift keeps the daily allowance from its entry day.
            # Midnight changes the reporting date, never resets normal hours.
            workday = left.astimezone(tz).date()
            week = workday - timedelta(days=workday.weekday())
            while left < right:
                local_day = left.astimezone(tz).date()
                midnight = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=tz)
                stop = min(right, midnight)
                hours = (stop - left).total_seconds() / 3600
                normal = min(hours, max(0, daily_hours - daily_normal[workday]),
                             max(0, weekly_hours - weekly_normal[week]))
                daily_normal[workday] += normal
                weekly_normal[week] += normal
                days[local_day] += hours
                extra_by_day[local_day] += max(0, hours - normal)
                left = stop

        def relevant(stamp):
            return start <= stamp < end

        for row in records:
            if row['kind'] == 'entrada':
                if opened is not None:
                    if relevant(row['stamp']):
                        pending.append(row['id'])
                        anomalies.append({'id': row['id'], 'reason': 'Entrada sem saída anterior.'})
                else:
                    opened = row
            elif row['kind'] == 'saida':
                if opened is None:
                    if relevant(row['stamp']):
                        pending.append(row['id'])
                        anomalies.append({'id': row['id'], 'reason': 'Saída sem entrada anterior.'})
                else:
                    allocate(opened['stamp'], row['stamp'])
                    opened = None
        # An unresolved shift can affect every month from its start onwards.
        reference = now or datetime.now(start.tzinfo)
        open_stamp = opened['stamp'] if opened and opened['stamp'] < end and reference >= start else None
        if open_stamp is not None:
            pending.append(opened['id'])
            if now is not None and now > open_stamp:
                allocate(open_stamp, now)
        month_days = {}
        overtime = 0.0
        for day, hours in sorted(days.items()):
            stamp = datetime.combine(day, time.min, tzinfo=tz)
            if start <= stamp < end:
                month_days[day.isoformat()] = hours
                overtime += extra_by_day[day]
        if month_days or open_stamp is not None or anomalies:
            result[employee_id] = {
                'days': month_days, 'total': sum(month_days.values()),
                'overtime': overtime, 'overtime_by_day':{day:extra_by_day[date.fromisoformat(day)] for day in month_days}, 'open': open_stamp,
                'pending_entry_ids': pending, 'anomalies': anomalies,
            }
    return result


def payroll_months(connection, months, profiles, tz, daily_hours=8, weekly_hours=44, employee_id=None, now=None):
    """Read/pair once, retaining weekly context and any older unresolved entry."""
    from app.database import PostgresConnection
    months=sorted(set(months))
    if not months:return {}
    start=datetime.fromisoformat(months[0]+'-01').replace(tzinfo=tz)
    last=date.fromisoformat(months[-1]+'-01')
    end=datetime(last.year+(last.month==12),last.month%12+1,1,tzinfo=tz)
    context=start-timedelta(days=start.weekday())
    postgres=isinstance(connection,PostgresConnection)
    stamp='EXTRACT(EPOCH FROM effective_at::timestamptz)' if postgres else 'julianday(effective_at)'
    bound='?' if postgres else 'julianday(?)'
    lower=context.timestamp() if postgres else context.isoformat()
    upper=end.timestamp() if postgres else end.isoformat()
    scoped=' AND employee_id=?' if employee_id is not None else ''
    params=((employee_id,) if employee_id is not None else ())+(lower,upper,upper,lower)
    # Last exit is a pairing reset. Only unmatched entries before the weekly
    # context are carried; completed shifts from older years stay in the DB.
    entries=[dict(row) for row in connection.execute(f"""
      WITH dated AS (
        SELECT id,employee_id,kind,effective_at AS at,{stamp} AS stamp
        FROM effective_time_entries WHERE accepted=1{scoped}
      ), exits AS (
        SELECT employee_id,id,stamp,ROW_NUMBER() OVER(PARTITION BY employee_id ORDER BY stamp DESC,id DESC) AS position
        FROM dated WHERE kind='saida' AND stamp<{bound}
      ), following_exits AS (
        SELECT employee_id,id,ROW_NUMBER() OVER(PARTITION BY employee_id ORDER BY stamp,id) AS position
        FROM dated WHERE kind='saida' AND stamp>={bound}
      )
      SELECT t.id,t.employee_id,t.kind,t.at FROM dated t
      LEFT JOIN exits x ON x.employee_id=t.employee_id AND x.position=1
      LEFT JOIN following_exits f ON f.employee_id=t.employee_id AND f.position=1
      WHERE (t.stamp<{bound} AND (t.stamp>={bound} OR
        (t.kind='entrada' AND (x.id IS NULL OR t.stamp>x.stamp OR (t.stamp=x.stamp AND t.id>x.id))))) OR t.id=f.id
      ORDER BY t.employee_id,t.stamp,t.id
    """,params)]
    combined=summarize(entries,start,end,tz,daily_hours,weekly_hours,contracts=profiles)
    stamps={row['id']:datetime.fromisoformat(row['at']).astimezone(tz) for row in entries}
    output={month:{} for month in months};reference=now or datetime.now(tz)
    for eid,record in combined.items():
        for month in months:
            first=datetime.fromisoformat(month+'-01').replace(tzinfo=tz)
            finish=datetime(first.year+(first.month==12),first.month%12+1,1,tzinfo=tz)
            days={day:hours for day,hours in record['days'].items() if day.startswith(month)}
            extra={day:record['overtime_by_day'][day] for day in days}
            opened=record['open'] if record['open'] and record['open']<finish and reference>=first else None
            anomalies=[item for item in record['anomalies'] if first<=stamps[item['id']]<finish]
            pending=[item['id'] for item in anomalies]
            if opened:
                pending.extend(entry for entry in record['pending_entry_ids'] if stamps[entry]==opened)
            if days or opened or anomalies:
                output[month][eid]=dict(days=days,total=sum(days.values()),overtime=sum(extra.values()),
                    overtime_by_day=extra,open=opened,pending_entry_ids=sorted(set(pending)),anomalies=anomalies)
    return output
