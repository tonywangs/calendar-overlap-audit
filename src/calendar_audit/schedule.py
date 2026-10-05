"""Strict custom schedule v2; no RFC 7953 import or inferred holidays."""
from datetime import date
import json
import re

from .core import AuditError, DAY, WEEKDAYS

SPEC_BYTES = 16384
WINDOWS_PER_DAY = 16
DECLARED_WINDOWS = 256
EXCEPTIONS = 90
KEYS = {'version', 'start', 'end', 'timezone', 'weekly', 'exceptions',
        'minimum_seconds', 'all_day'}
SCHEDULE_LIMITS = dict(schedule_bytes=SPEC_BYTES, windows_per_declaration=WINDOWS_PER_DAY,
                       declared_windows=DECLARED_WINDOWS, exceptions=EXCEPTIONS,
                       effective_windows=90 * WINDOWS_PER_DAY)


def validate_windows(value):
    if not isinstance(value, list):
        raise AuditError('Schedule windows must be arrays of [start, end] pairs')
    if len(value) > WINDOWS_PER_DAY:
        raise AuditError('windows_per_declaration limit exceeded (16)')
    result = []
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise AuditError('Schedule window must be a [start, end] pair')
        for i, clock in enumerate(pair):
            if not isinstance(clock, str) or not (re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', clock)
                                                   or (i == 1 and clock == '24:00')):
                raise AuditError('Schedule times must be HH:MM; only an end permits 24:00')
        if pair[0] >= pair[1]:
            raise AuditError('Window end must be later than start; overnight working windows are unsupported')
        result.append(pair.copy())
    result.sort()
    if any(a[1] > b[0] for a, b in zip(result, result[1:])):
        raise AuditError('Overlapping or duplicate schedule windows are unsupported')
    return result


def validate_schedule(value, max_days):
    # Reuse v1's common field validation without extending its public contract.
    from .availability import validate_spec
    if set(value) != KEYS:
        raise AuditError('Schedule must contain exactly the version-2 keys; see docs/schedules-v2.md')
    common = {k: value[k] for k in ('start', 'end', 'timezone', 'minimum_seconds', 'all_day')}
    validate_spec(dict(common, version=1, weekdays=['MO'], work_start='00:00', work_end='24:00'), max_days)
    weekly = value['weekly']
    if not isinstance(weekly, dict) or any(k not in WEEKDAYS for k in weekly):
        raise AuditError('weekly must map weekday names MO,TU,WE,TH,FR,SA,SU to windows')
    weekly = {k: validate_windows(weekly[k]) for k in WEEKDAYS if k in weekly}
    exceptions = value['exceptions']
    if not isinstance(exceptions, list):
        raise AuditError('exceptions must be an array')
    if len(exceptions) > EXCEPTIONS:
        raise AuditError('exceptions limit exceeded (90)')
    seen, normalized = set(), []
    for item in exceptions:
        if not isinstance(item, dict) or set(item) != {'date', 'windows'}:
            raise AuditError('Exception must contain exactly date and windows')
        raw = item['date']
        try:
            if not isinstance(raw, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', raw):
                raise ValueError()
            date.fromisoformat(raw)
        except ValueError as exc:
            raise AuditError('Exception date must be a valid YYYY-MM-DD date') from exc
        if raw in seen:
            raise AuditError('Duplicate exception date')
        if not value['start'] <= raw < value['end']:
            raise AuditError('Exception date must be inside the schedule horizon')
        seen.add(raw)
        normalized.append(dict(date=raw, windows=validate_windows(item['windows'])))
    if sum(map(len, weekly.values())) + sum(len(e['windows']) for e in normalized) > DECLARED_WINDOWS:
        raise AuditError('declared_windows limit exceeded (256)')
    result = dict(common, version=2, weekly=weekly, exceptions=sorted(normalized, key=lambda e: e['date']))
    if len(json.dumps(result, ensure_ascii=True, separators=(',', ':')).encode()) > SPEC_BYTES:
        raise AuditError('schedule_bytes limit exceeded (16384)')
    return result


def effective_schedule(spec, zone, budget):
    from .availability import boundary
    replacements = {e['date']: e['windows'] for e in spec['exceptions']}
    working, days = [], []
    day, last = date.fromisoformat(spec['start']), date.fromisoformat(spec['end'])
    names = list(WEEKDAYS)
    while day < last:
        budget.check()
        raw = day.isoformat()
        weekly = spec['weekly'].get(names[day.weekday()], [])
        selected = replacements.get(raw, weekly)
        resolved = []
        for start, end in selected:
            budget.check()
            lo, hi = boundary(day, start, zone), boundary(day, end, zone)
            if lo >= hi:
                raise AuditError('Effective window must have positive elapsed duration')
            if resolved and resolved[-1][1] == lo:
                resolved[-1] = (resolved[-1][0], hi)
            else:
                resolved.append((lo, hi))
        working.extend((day, lo, hi) for lo, hi in resolved)
        days.append(dict(id='d' + raw, date=raw, weekday=names[day.weekday()],
                         weekly_windows=weekly, replacement=replacements.get(raw),
                         applied_exception=raw in replacements, declared_windows=selected))
        day += DAY
    # Guard the index's sorted, nonoverlapping UTC precondition across dates too.
    if any(a[2] > b[1] for a, b in zip(working, working[1:])):
        raise AuditError('Effective working windows overlap in UTC')
    return working, days


def explain_days(report, days, budget):
    by_date = {d['date']: [] for d in days}
    gaps = {d['date']: 0 for d in days}
    for w in report['windows']:
        by_date[w['date']].append(w)
        w['schedule_day'] = 'd' + w['date']
    for g in report['candidates']:
        gaps[g['date']] += g['seconds']
    complete = report['complete']
    for day in days:
        budget.check()
        windows = by_date[day['date']]
        working = sum(w['seconds'] for w in windows)
        observed = sum(b['seconds'] for w in windows for b in w['busy'])
        candidate = gaps[day['date']]
        status = ('closed' if not windows else 'incomplete' if not complete else
                  'fully_booked' if observed == working else 'available' if candidate else 'below_minimum')
        day.update(windows=[w['id'] for w in windows], analysis_complete=complete, status=status,
                   working_seconds=working, observed_occupied_seconds=observed,
                   occupied_seconds=observed if complete else None,
                   free_seconds=working-observed if complete else None,
                   candidate_seconds=candidate if complete else None)
    report['days'] = days
    for field in ('working_seconds', 'observed_occupied_seconds', 'occupied_seconds', 'free_seconds'):
        report[field] = sum(d[field] for d in days) if complete or field in (
            'working_seconds', 'observed_occupied_seconds') else None
    report['limits'].update(SCHEDULE_LIMITS)
    return report
