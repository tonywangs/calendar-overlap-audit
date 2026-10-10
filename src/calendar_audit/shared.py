"""Auditable set algebra over asserted coverage, working schedules and occupancy."""
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from .availability import boundary
from .core import AuditError, Budget, DAY, WEEKDAYS, get_zone, iso
from .shared_input import SharedLimits, fingerprint, instant, load_manifest, parse_freebusy, read_local

LIMITATIONS = [
    'Candidate windows are not booked meetings or a guarantee of willingness to meet.',
    'Complete occupancy and sole ownership are operator assertions, not independently established facts.',
    'Uncovered time is unknown. FREE never overrides busy; all supported busy types block.',
    'No freshness or revision precedence is inferred. Conflicting complete sources are unioned conservatively.',
    'Working hours are explicit weekly schedules; holidays and date exceptions are not inferred.',
    'Provider interoperability, human usability and real participant availability remain unvalidated.',
    'Aliases, exact times, working schedules and input hashes may disclose sensitive information.',
]


def union(intervals, budget):
    # Charge a conservative comparison allowance for sorting, in addition to scans.
    budget.take('operations', len(intervals) * max(1, len(intervals).bit_length()))
    result = []
    for a, b in sorted(intervals):
        budget.take('operations')
        if a >= b:
            continue
        if result and a <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], b))
        else:
            result.append((a, b))
    return result


def intersect(left, right, budget):
    """Linear two-pointer intersection of sorted disjoint interval sets."""
    i = j = 0
    out = []
    while i < len(left) and j < len(right):
        budget.take('operations')
        a, b = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if a < b:
            out.append((a, b))
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return out


def subtract(left, right, budget):
    """Linear subtraction; right spans may cross several left spans."""
    result, j = [], 0
    for lo, hi in left:
        budget.take('operations')
        while j < len(right) and right[j][1] <= lo:
            budget.take('operations')
            j += 1
        cursor, k = lo, j
        while k < len(right) and right[k][0] < hi:
            budget.take('operations')
            a, b = right[k]
            if a > cursor:
                result.append((cursor, min(a, hi)))
            cursor = max(cursor, b)
            if b >= hi:
                break
            k += 1
        if cursor < hi:
            result.append((cursor, hi))
        j = k
    return result


def working(person, lo, hi, budget):
    zone = get_zone(person['timezone'])
    # One previous local date captures overnight spill into the horizon.
    day = lo.astimezone(zone).date() - DAY
    last = hi.astimezone(zone).date()
    names, spans = list(WEEKDAYS), []
    while day <= last:
        budget.take('operations')
        for start, end in person['weekly'].get(names[day.weekday()], []):
            budget.take('operations')
            a = boundary(day, start, zone)
            b = boundary(day + DAY if end < start else day, end, zone)
            if a >= b:
                raise AuditError('Working shift must have positive elapsed duration')
            if max(a, lo) < min(b, hi):
                spans.append((max(a, lo), min(b, hi)))
        day += DAY
    return union(spans, budget)


def record(pair, budget):
    budget.take('intervals')
    a, b = pair
    return dict(start=iso(a), end=iso(b), seconds=int((b-a).total_seconds()))


def discover(manifest_path, limits=SharedLimits(), budget=None):
    """All-or-nothing analysis. Unknown coverage is normal and reported explicitly."""
    budget = budget or Budget(limits)
    manifest_path = Path(manifest_path)
    spec, manifest_source = load_manifest(manifest_path, budget)
    lo, hi = instant(spec['start']), instant(spec['end'])
    horizon, common, participants, owners = [(lo, hi)], [(lo, hi)], [], {}
    for number, person in enumerate(spec['participants'], 1):
        budget.check()
        pid = f'p{number}'
        coverage, busy, sources = [], [], []
        for index, source in enumerate(person['sources'], 1):
            budget.take('files')
            path = manifest_path.parent / source['path']
            raw, identity = read_local(path, limits.input_bytes - budget.counts['input_bytes'], budget)
            if identity in owners and owners[identity] != pid:
                raise AuditError('A source file cannot have multiple participant owners')
            owners[identity] = pid
            bounds, blocks, counts = parse_freebusy(raw, budget)
            coverage.append(bounds)
            busy.extend(blocks)
            sources.append(dict(id=f'{pid}s{index}', **fingerprint(raw), complete_occupancy=True,
                                coverage=record(bounds, budget), period_counts=counts))
        coverage = intersect(union(coverage, budget), horizon, budget)
        busy = intersect(union(busy, budget), horizon, budget)
        shifts = working(person, lo, hi, budget)
        known_working = intersect(shifts, coverage, budget)
        free = subtract(known_working, busy, budget)
        gaps = subtract(horizon, coverage, budget)
        common = intersect(common, free, budget)
        participant = dict(id=pid, alias=person['alias'], timezone=person['timezone'],
                           weekly={day: sorted(person['weekly'].get(day, [])) for day in WEEKDAYS}, sources=sources)
        for key, values in [('coverage', coverage), ('coverage_gaps', gaps), ('busy', busy),
                            ('working', shifts), ('known_working', known_working), ('free', free)]:
            participant[key] = [record(pair, budget) for pair in values]
        participant['coverage_complete'] = not gaps
        participants.append(participant)
    windows = []
    for a, b in union(common, budget):
        if (b-a).total_seconds() < spec['duration_seconds']:
            continue
        budget.take('windows')
        latest = b-timedelta(seconds=spec['duration_seconds'])
        local = []
        for person in participants:
            budget.take('operations')
            zone = get_zone(person['timezone'])
            local.append(dict(participant=person['id'], start=a.astimezone(zone).isoformat(),
                              end=b.astimezone(zone).isoformat(), latest_start=latest.astimezone(zone).isoformat()))
        windows.append(dict(id=f'w{len(windows)+1}', **record((a, b), budget), latest_start=iso(latest), local=local))
    budget.check()
    return dict(schema_version=1, report_type='shared-windows', complete=True,
                coverage_complete=all(p['coverage_complete'] for p in participants),
                horizon=record((lo, hi), budget), duration_seconds=spec['duration_seconds'],
                manifest_source=manifest_source, participants=participants, windows=windows,
                window_seconds=sum(w['seconds'] for w in windows), limitations=LIMITATIONS.copy(),
                limits=asdict(limits), timezone_database='tzdata 2025.2')
