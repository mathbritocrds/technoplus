"""Pair accepted clock records globally before allocating local days and overtime."""
from collections import defaultdict
from datetime import datetime, time, timedelta


def summarize(entries, start, end, tz, daily_hours=8, weekly_hours=44, now=None):
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
        opened = None
        anomalies = []
        pending = []

        def allocate(left, right):
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
                'overtime': overtime, 'open': open_stamp,
                'pending_entry_ids': pending, 'anomalies': anomalies,
            }
    return result
