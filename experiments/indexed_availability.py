"""Versioned working windows and conservative, auditable interval complements."""
from bisect import bisect_left, bisect_right
from heapq import merge
from dataclasses import asdict
from datetime import date, datetime, time
import hashlib
import json
from pathlib import Path
import re
import stat

from .core import AuditError, Budget, DAY, Limits, UTC, WEEKDAYS, analyze, analyze_occurrences, get_zone, iso, window

KEYS = {'version', 'start', 'end', 'timezone', 'weekdays', 'work_start', 'work_end',
        'minimum_seconds', 'all_day'}


def validate_spec(value, max_days=90):
    if type(max_days) is not int or not 1 <= max_days <= 90:
        raise AuditError('max-days must be an integer from 1 to 90')
    if not isinstance(value, dict) or set(value) != KEYS:
        raise AuditError('Availability spec must contain exactly the version-1 keys; see docs/availability-v1.md')
    if type(value['version']) is not int or value['version'] != 1:
        raise AuditError('Availability spec version must be 1')
    for key in ('start', 'end', 'timezone', 'work_start', 'work_end', 'all_day'):
        if not isinstance(value[key], str):
            raise AuditError(f'Spec {key} must be a string')
    days = value['weekdays']
    if (not isinstance(days, list) or not days or
            any(not isinstance(d, str) or d not in WEEKDAYS for d in days) or len(set(days)) != len(days)):
        raise AuditError('weekdays must be unique weekday names MO,TU,WE,TH,FR,SA,SU')
    minutes = []
    for key in ('work_start', 'work_end'):
        raw = value[key]
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', raw) and not (key == 'work_end' and raw == '24:00'):
            raise AuditError(f'{key} must be HH:MM; only work_end permits 24:00')
        h, m = map(int, raw.split(':'))
        minutes.append(h * 60 + m)
    if minutes[0] >= minutes[1]:
        raise AuditError('work_end must be later than work_start; overnight working windows are unsupported')
    if type(value['minimum_seconds']) is not int or not 1 <= value['minimum_seconds'] <= 90 * 86400:
        raise AuditError('minimum_seconds must be an integer from 1 to 7776000')
    if value['all_day'] not in ('block', 'ignore'):
        raise AuditError('all_day must explicitly be block or ignore')
    zone = get_zone(value['timezone'])
    first, last, _, _ = window(value['start'], value['end'], zone)
    if (last - first).days > max_days:
        raise AuditError('Date range exceeds max-days limit')
    return {**value, 'weekdays': sorted(days, key=WEEKDAYS.get)}


def load_spec(path, max_days=90):
    path = Path(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise AuditError('Spec must be a regular local file')
    with path.open('rb') as source:
        raw = source.read(16385)
    if len(raw) > 16384:
        raise AuditError('Spec exceeds 16384 bytes')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AuditError('Duplicate spec key')
            result[key] = value
        return result
    try:
        parsed = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AuditError('Spec must be a UTF-8 JSON object') from exc
    return validate_spec(parsed, max_days), {
        'name': path.name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def boundary(day, clock, zone):
    if clock == '24:00':
        day, clock = day + DAY, '00:00'
    naive = datetime.combine(day, time.fromisoformat(clock))
    try:
        instants = {naive.replace(tzinfo=zone, fold=f).astimezone(UTC) for f in (0, 1)
                    if naive.replace(tzinfo=zone, fold=f).astimezone(UTC).astimezone(zone).replace(tzinfo=None) == naive}
    except OverflowError as exc:
        raise AuditError('Working boundary is outside representable UTC dates') from exc
    if len(instants) != 1:
        kind = 'Nonexistent' if not instants else 'Ambiguous'
        raise AuditError(f'{kind} boundary {day.isoformat()} {clock} in {zone.key}; change working hours, date range, or timezone')
    return instants.pop()


def interval(a, b, zone):
    return {'start': iso(a), 'end': iso(b), 'local_start': a.astimezone(zone).isoformat(),
            'local_end': b.astimezone(zone).isoformat(), 'seconds': int((b - a).total_seconds())}


def complement(lo, hi, busy, minimum, budget, *, presorted=False):
    """Merge clipped intervals; preserve contributors and endpoint witnesses."""
    merged = []
    for a, b, ident in (busy if presorted else sorted(busy)):
        budget.check()
        a, b = max(a, lo), min(b, hi)
        if a >= b:
            continue
        if not merged or a > merged[-1]['b']:
            merged.append({'a': a, 'b': b, 'members': [ident], 'left': [ident], 'right': [ident]})
        else:
            block = merged[-1]
            block['members'].append(ident)
            if a == block['a']:
                block['left'].append(ident)
            if b > block['b']:
                block['b'], block['right'] = b, [ident]
            elif b == block['b']:
                block['right'].append(ident)
    cursor, left, gaps = lo, [], []
    for block in merged:
        budget.check()
        if (block['a'] - cursor).total_seconds() >= minimum:
            gaps.append((cursor, block['a'], left, block['left']))
        cursor, left = block['b'], block['right']
    if (hi - cursor).total_seconds() >= minimum:
        gaps.append((cursor, hi, left, []))
    return merged, gaps


def indexed_busy(working, occurrences, all_day_policy, budget):
    """Bucket into sorted, nonoverlapping windows, retaining raw tuple order.

    The caller supplies chronological positive-duration UTC windows. Bisect
    excludes touching endpoints. Dates are indexed separately for all-day data;
    repeated dates support split windows without adding a public spec version.
    Storage includes one reference per occurrence/window intersection.
    """
    starts = [lo for _, lo, _ in working]
    ends = [hi for _, _, hi in working]
    dates = [day.isoformat() for day, _, _ in working]
    timed, days = [], []
    for occurrence in occurrences:
        budget.check()
        if occurrence['all_day']:
            if all_day_policy == 'block':
                days.append(occurrence)
        else:
            timed.append((datetime.fromisoformat(occurrence['start']),
                          datetime.fromisoformat(occurrence['end']), occurrence['id']))
    budget.check()
    timed.sort()
    days.sort(key=lambda o: o['id'])
    budget.check()
    buckets = [[] for _ in working]
    day_buckets = [[] for _ in working]
    for item in timed:
        budget.check()
        a, b, _ = item
        if a >= b:
            continue
        for index in range(bisect_right(ends, a), bisect_left(starts, b)):
            budget.check()
            buckets[index].append(item)
    for occurrence in days:
        budget.check()
        for index in range(bisect_left(dates, occurrence['start']),
                           bisect_left(dates, occurrence['end'])):
            budget.check()
            _, lo, hi = working[index]
            day_buckets[index].append((lo, hi, occurrence['id']))
    for timed_bucket, day_bucket in zip(buckets, day_buckets):
        budget.check()
        yield merge(timed_bucket, day_bucket)


def availability(paths, spec, limits=Limits(), budget=None, spec_source=None, max_days=90, *, include_overlaps=False):
    spec = validate_spec(spec, max_days)
    budget = budget or Budget(limits)
    zone = get_zone(spec['timezone'])
    first, last = date.fromisoformat(spec['start']), date.fromisoformat(spec['end'])
    boundary(first, '00:00', zone)
    boundary(last, '00:00', zone)
    working = []
    day = first
    while day < last:
        budget.check()
        if day.weekday() in {WEEKDAYS[d] for d in spec['weekdays']}:
            working.append((day, boundary(day, spec['work_start'], zone), boundary(day, spec['work_end'], zone)))
        day += DAY
    analyze_input = analyze if include_overlaps else analyze_occurrences
    audit = analyze_input(paths, spec['start'], spec['end'], spec['timezone'], limits, budget)
    windows, candidates = [], []
    selected = indexed_busy(working, audit['occurrences'], spec['all_day'], budget)
    for (day, lo, hi), busy in zip(working, selected):
        budget.check()
        merged, gaps = complement(lo, hi, busy, spec['minimum_seconds'], budget, presorted=True)
        wid = f'w{len(windows) + 1}'
        blocks = [{**interval(b['a'], b['b'], zone), 'occurrences': sorted(b['members']),
                   'start_occurrences': sorted(b['left']), 'end_occurrences': sorted(b['right'])} for b in merged]
        windows.append({'id': wid, 'date': day.isoformat(), **interval(lo, hi, zone), 'busy': blocks})
        if audit['complete']:
            for a, b, left, right in gaps:
                candidates.append({'id': f'g{len(candidates) + 1}', 'window': wid, 'date': day.isoformat(),
                                   **interval(a, b, zone), 'before': sorted(left), 'after': sorted(right)})
    budget.check()
    applicable_limits = asdict(limits)
    if not include_overlaps:
        del applicable_limits['pairs']
    return {'schema_version': 1 if include_overlaps else 2, 'report_type': 'availability', 'spec': spec, 'spec_source': spec_source,
            'complete': audit['complete'], 'scope': 'Only supplied exports and selected policies; not a booking guarantee.',
            'limits': {**applicable_limits, 'days': max_days}, 'windows': windows, 'candidates': candidates,
            'candidate_seconds': sum(g['seconds'] for g in candidates) if audit['complete'] else None, 'audit': audit}
