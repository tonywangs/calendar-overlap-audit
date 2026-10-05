"""Public schedules checked from raw inputs against an independent endpoint oracle."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import random

import pytest

from calendar_audit.availability import availability, load_spec, validate_spec
from calendar_audit.core import AuditError, Budget, Limits
from calendar_audit.availability_report import html_bytes
from calendar_audit.report import json_bytes
from test_availability import timed, stamp
from test_indexed_availability import oracle, check_report

SPEC2 = dict(version=2, start='2026-03-06', end='2026-03-09', timezone='UTC',
             weekly={'FR': [['09:00', '12:00'], ['13:00', '17:00']]},
             exceptions=[{'date': '2026-03-07', 'windows': [['10:00', '12:00']]},
                         {'date': '2026-03-08', 'windows': []}],
             minimum_seconds=1800, all_day='block')
NAMES = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
UTC = timezone.utc


def clock(minutes):
    return f'{minutes//60:02d}:{minutes%60:02d}'


def expected_instant(day, minutes, zone):
    """Explicit 2026 US transition offsets; no production boundary/ZoneInfo calls."""
    if zone == 'UTC':
        offset = 0
    elif day.month == 3:
        offset = 4 if day > date(2026, 3, 8) or day == date(2026, 3, 8) and minutes >= 180 else 5
    else:
        offset = 5 if day > date(2026, 11, 1) or day == date(2026, 11, 1) and minutes >= 120 else 4
    return datetime.combine(day, datetime.min.time(), UTC) + timedelta(minutes=minutes, hours=offset)


def minutes(clock):
    a, b = map(int, clock.split(':'))
    return a*60+b


def random_windows(rng):
    endpoints = sorted(rng.sample([0, 240, 480, 540, 600, 660, 720, 780, 840, 900, 960, 1020, 1080, 1440],
                                 rng.choice([0, 2, 4, 6, 8])))
    result = [[clock(a), clock(b)] for a, b in zip(endpoints[::2], endpoints[1::2])]
    # Split a declared interval at a valid boundary to test adjacent normalization.
    if result and minutes(result[-1][1])-minutes(result[-1][0]) >= 120 and rng.randrange(2):
        a, b = result.pop()
        mid = clock(minutes(b)-60)
        if minutes(mid) >= 240:
            result.extend([[a, mid], [mid, b]])
        else:
            result.append([a, b])
    rng.shuffle(result)
    return result


@pytest.mark.parametrize('seed', range(256))
def test_seeded_schedule_raw_input_oracle(seed, make_ics):
    rng = random.Random(20261005+seed)
    first = [date(2026, 3, 7), date(2026, 10, 31), date(2026, 3, 6), date(2026, 1, 1)][seed%4]
    days = [first+timedelta(days=i) for i in range(3)]
    zone = 'America/New_York' if seed%4 < 2 else 'UTC'
    weekly = {name: random_windows(rng) for name in NAMES}
    exceptions = [{'date': d.isoformat(), 'windows': [] if i == seed%3 else random_windows(rng)}
                  for i, d in enumerate(days) if rng.randrange(3) != 0]
    spec = dict(SPEC2, start=str(first), end=str(first+timedelta(days=3)), timezone=zone,
                weekly=weekly, exceptions=exceptions, minimum_seconds=rng.choice([1, 60, 1800, 3600, 20000]),
                all_day='block' if seed%2 else 'ignore')
    original_spec = deepcopy(spec)
    lo = datetime.combine(first, datetime.min.time(), UTC)
    events, raw_busy = [], []
    for i in range(rng.randrange(5, 30)):
        a = lo + timedelta(seconds=rng.choice([0, 86400, rng.randrange(-86400, 3*86400)]))
        b = a + timedelta(seconds=rng.choice([0, 3600, 7200, rng.randrange(1, 86400)]))
        extra = rng.choice(['', '', '', 'TRANSP:TRANSPARENT', 'STATUS:CANCELLED'])
        events.append(timed(str(i), a, b, extra) if a < b else f'UID:{i}\nDTSTART:{stamp(a)}\n{extra}')
        if not extra and a < b:
            raw_busy.append((a, b, str(i)))
    # Known recurrence expansion, independent of the reported occurrence list.
    origin = lo+timedelta(hours=10)
    events.append(timed('series', origin, origin+timedelta(hours=1), 'RRULE:FREQ=DAILY;COUNT=3'))
    target = origin+timedelta(days=1)
    mode = seed%3
    change = ['STATUS:CANCELLED', f'DTSTART:{stamp(target+timedelta(hours=4))}',
              f'DTSTART:{stamp(target)}\nTRANSP:TRANSPARENT'][mode]
    events.append(f'UID:series\nRECURRENCE-ID:{stamp(target)}\n{change}')
    raw_busy.extend((origin+timedelta(days=i), origin+timedelta(days=i, hours=1), f'series{i}') for i in [0, 2])
    if mode == 1:
        raw_busy.append((target+timedelta(hours=4), target+timedelta(hours=5), 'moved'))
    events.append(f'UID:day\nDTSTART;VALUE=DATE:{days[1]:%Y%m%d}\nDTEND;VALUE=DATE:{days[2]:%Y%m%d}')
    rng.shuffle(events)
    source = make_ics(*events)
    before = source.read_bytes()
    report = availability([source], spec, include_overlaps=seed%7 == 0)
    assert report['complete'] and report['schema_version'] == 3, report['audit']['issues']
    expected_windows, expected_gaps, occupied = [], [], 0
    replacements = {e['date']: e['windows'] for e in exceptions}
    for day in days:
        declared = replacements.get(str(day), weekly[NAMES[day.weekday()]])
        intervals = [(expected_instant(day, minutes(a), zone), expected_instant(day, minutes(b), zone), str(i))
                     for i, (a, b) in enumerate(declared)]
        # Treat declared windows as occupied segments to compute their union.
        # This oracle sorts endpoints and tests containment, never production merging.
        merged, _ = oracle(lo-timedelta(days=1), lo+timedelta(days=5), intervals, 1)
        for part in merged:
            a, b = part['a'], part['b']
            expected_windows.append((str(day), a, b))
            busy = raw_busy + ([(a, b, 'day')] if day == days[1] and spec['all_day'] == 'block' else [])
            blocks, gaps = oracle(a, b, busy, spec['minimum_seconds'])
            occupied += sum(int((p['b']-p['a']).total_seconds()) for p in blocks)
            expected_gaps.extend((str(day), x, y) for x, y, _, _ in gaps)
    assert [(w['date'], datetime.fromisoformat(w['start']), datetime.fromisoformat(w['end']))
            for w in report['windows']] == expected_windows
    assert [(g['date'], datetime.fromisoformat(g['start']), datetime.fromisoformat(g['end']))
            for g in report['candidates']] == expected_gaps
    assert report['occupied_seconds'] == occupied
    assert report['free_seconds'] == report['working_seconds']-occupied
    assert report['candidate_seconds'] == sum(int((b-a).total_seconds()) for _, a, b in expected_gaps)
    check_report(report)  # Independent provenance/endpoint witness assertions too.
    for day in report['days']:
        assert day['applied_exception'] == (day['date'] in replacements)
        assert day['replacement'] == (sorted(replacements[day['date']]) if day['applied_exception'] else None)
        assert day['occupied_seconds'] <= day['working_seconds']
    repeated = availability([source], spec, include_overlaps=seed%7 == 0)
    assert json_bytes(repeated) == json_bytes(report)
    assert html_bytes(repeated, Budget(Limits())) == html_bytes(report, Budget(Limits()))
    assert source.read_bytes() == before and spec == original_spec


def test_replacements_closure_weekend_and_statuses(make_ics):
    source = make_ics('UID:booked\nDTSTART:20260306T000000Z\nDTEND:20260307T000000Z')
    report = availability([source], SPEC2)
    assert [d['status'] for d in report['days']] == ['fully_booked', 'available', 'closed']
    assert report['working_seconds'] == 9*3600 and report['occupied_seconds'] == 7*3600
    assert report['candidate_seconds'] == 2*3600
    below = availability([source], dict(SPEC2, minimum_seconds=7201))
    assert below['days'][1]['status'] == 'below_minimum' and below['free_seconds'] == 7200
    closed = availability([source], dict(SPEC2, weekly={}, exceptions=[]))
    assert all(d['status'] == 'closed' for d in closed['days']) and closed['candidate_seconds'] == 0


def test_adjacent_merge_minimum_exact_boundaries_and_breaks(make_ics):
    spec = dict(SPEC2, end='2026-03-07', exceptions=[], minimum_seconds=7200,
                weekly={'FR': [['13:00', '14:00'], ['10:00', '11:00'], ['09:00', '10:00']]})
    source = make_ics('UID:left\nDTSTART:20260306T080000Z\nDTEND:20260306T090000Z',
                      'UID:break\nDTSTART:20260306T110000Z\nDTEND:20260306T130000Z',
                      'UID:right\nDTSTART:20260306T140000Z\nDTEND:20260306T150000Z')
    report = availability([source], spec)
    assert [w['seconds'] for w in report['windows']] == [7200, 3600]
    assert [g['seconds'] for g in report['candidates']] == [7200]
    assert report['occupied_seconds'] == 0 and report['free_seconds'] == 10800


@pytest.mark.parametrize('day,bad,kind', [('2026-03-08', '02:30', 'Nonexistent'),
                                         ('2026-11-01', '01:30', 'Ambiguous')])
@pytest.mark.parametrize('position', ['start', 'end', 'shared'])
@pytest.mark.parametrize('replacement', [False, True])
def test_reject_all_effective_dst_boundaries(make_ics, day, bad, kind, position, replacement):
    windows = {'start': [[bad, '04:00']], 'end': [['00:00', bad]],
               'shared': [['00:00', bad], [bad, '04:00']]}[position]
    spec = dict(SPEC2, start=day, end=str(date.fromisoformat(day)+timedelta(days=1)),
                timezone='America/New_York', weekly={'SU': windows}, exceptions=[])
    if replacement:
        spec.update(weekly={}, exceptions=[dict(date=day, windows=windows)])
    with pytest.raises(AuditError, match=kind):
        availability([make_ics()], spec)
    spec['exceptions'] = [dict(date=day, windows=[])]
    assert availability([make_ics()], spec)['days'][0]['status'] == 'closed'


@pytest.mark.parametrize('start,end,seconds', [('2026-03-08', '2026-03-09', 3*3600),
                                            ('2026-11-01', '2026-11-02', 5*3600)])
def test_dst_elapsed_and_24_hour_end(make_ics, start, end, seconds):
    spec = dict(SPEC2, start=start, end=end, timezone='America/New_York',
                weekly={'SU': [['00:00', '04:00'], ['23:00', '24:00']]}, exceptions=[])
    report = availability([make_ics()], spec)
    assert [w['seconds'] for w in report['windows']] == [seconds, 3600]
    assert report['working_seconds'] == seconds+3600


def test_incomplete_never_looks_fully_booked(make_ics):
    source = make_ics('UID:bad\nDTSTART:20260306T090000Z\nRRULE:FREQ=MONTHLY')
    report = availability([source], SPEC2)
    assert [d['status'] for d in report['days']] == ['incomplete', 'incomplete', 'closed']
    assert not any(d['analysis_complete'] for d in report['days'])
    for field in ('occupied_seconds', 'free_seconds', 'candidate_seconds'):
        assert report[field] is None and all(d[field] is None for d in report['days'])
    assert report['candidates'] == []


@pytest.mark.parametrize('field,value', [
    ('version', True), ('version', 2.0), ('version', 3), ('weekly', []), ('weekly', {'MON': []}),
    ('weekly', {'FR': None}), ('weekly', {'FR': [['9:00', '12:00']]}),
    ('weekly', {'FR': [['24:00', '24:00']]}), ('weekly', {'FR': [['23:00', '01:00']]}),
    ('weekly', {'FR': [['09:00', '09:00']]}), ('weekly', {'FR': [['09:00', '25:00']]}),
    ('weekly', {'FR': [['09:00', '12:00'], ['11:00', '13:00']]}),
    ('weekly', {'FR': [['09:00', '12:00'], ['09:00', '12:00']]}),
    ('weekly', {'FR': [[None, '12:00']]}), ('weekly', {'FR': [['09:00']]}),
    ('exceptions', {}), ('exceptions', [dict(date='2026-03-06', windows=[], label='x')]),
    ('exceptions', [dict(date='2026-03-06', windows=[])]*2),
    ('exceptions', [dict(date='2026-03-09', windows=[])]),
    ('exceptions', [dict(date='2026-02-30', windows=[])]),
    ('exceptions', [dict(date='2026-3-6', windows=[])]),
    ('exceptions', [dict(date=True, windows=[])]), ('exceptions', [None]),
    ('minimum_seconds', True), ('minimum_seconds', 0), ('all_day', 'guess'),
    ('timezone', 'Unknown/Zone'), ('timezone', None), ('start', '2026-3-6'),
])
def test_invalid_schedules(field, value):
    with pytest.raises((AuditError, ValueError)):
        validate_spec(dict(SPEC2, **{field: value}))


@pytest.mark.parametrize('field', list(SPEC2))
def test_missing_keys(field):
    spec = deepcopy(SPEC2)
    del spec[field]
    with pytest.raises(AuditError):
        validate_spec(spec)


def test_extra_keys():
    with pytest.raises(AuditError):
        validate_spec(dict(SPEC2, weekdays=['MO']))


def test_count_limits_and_maximum_valid_schedule(make_ics):
    windows = [[clock(i*60), clock(i*60+30)] for i in range(16)]
    spec = dict(SPEC2, start='2026-01-01', end='2026-04-01',
                weekly={d: windows for d in NAMES}, exceptions=[])
    report = availability([make_ics()], spec)
    assert len(report['windows']) == 1440 and report['complete']
    with pytest.raises(AuditError, match='windows_per_declaration limit exceeded'):
        validate_spec(dict(spec, weekly={'MO': windows+[ ['20:00', '21:00'] ]}))
    exceptions = [dict(date=str(date(2026, 1, 1)+timedelta(days=i)), windows=windows) for i in range(10)]
    with pytest.raises(AuditError, match='declared_windows limit exceeded'):
        validate_spec(dict(spec, exceptions=exceptions))
    with pytest.raises(AuditError, match='exceptions limit exceeded'):
        validate_spec(dict(spec, exceptions=[dict(date='2026-01-01', windows=[])]*91))
    with pytest.raises(AuditError, match='max-days'):
        validate_spec(spec, 89)
    # 256 declared windows exactly, 90 dated exceptions exactly (empty counts too).
    exceptions = [dict(date=str(date(2026, 1, 1)+timedelta(days=i)), windows=windows if i < 9 else [])
                  for i in range(90)]
    assert len(validate_spec(dict(spec, exceptions=exceptions))['exceptions']) == 90


@pytest.mark.parametrize('raw', [b'{"version":2,"version":2}',
    b'{"weekly":{"MO":[],"MO":[]}}', b' ' * 16385, b'\xff', b'[' * 2000])
def test_bad_schedule_file(tmp_path, raw):
    path = tmp_path/'schedule.json'
    path.write_bytes(raw)
    with pytest.raises(AuditError):
        load_spec(path)


def test_exact_schedule_file_byte_bound(tmp_path):
    path = tmp_path/'schedule.json'
    raw = json.dumps(SPEC2).encode()
    path.write_bytes(raw+b' '*(16384-len(raw)))
    assert load_spec(path)[0]['version'] == 2
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(AuditError, match='16384'):
        load_spec(path)


@pytest.fixture(scope='module')
def frozen_index(tmp_path_factory):
    from index_experiment import load_availability
    return load_availability(tmp_path_factory.mktemp('v1-index'), True)


@pytest.mark.parametrize('seed', range(32))
def test_public_v1_exact_frozen_index_equivalence(seed, make_ics, frozen_index):
    from test_availability import SPEC
    import importlib
    frozen_html = importlib.import_module(frozen_index.__package__+'.availability_report').html_bytes
    rng = random.Random(seed)
    lo = datetime(2026, 3, 6, tzinfo=UTC)
    events = [timed(str(i), lo+timedelta(minutes=a), lo+timedelta(minutes=a+60))
              for i, a in enumerate(rng.sample(range(3*1440), 20))]
    source = make_ics(*events)
    spec = dict(SPEC, end='2026-03-09', minimum_seconds=rng.choice([1, 900, 3600]))
    for legacy in (False, True):
        actual = availability([source], spec, include_overlaps=legacy)
        expected = frozen_index.availability([source], spec, include_overlaps=legacy)
        assert json_bytes(actual) == json_bytes(expected)
        assert html_bytes(actual, Budget(Limits())) == frozen_html(expected, frozen_index.Budget(frozen_index.Limits()))


def test_budget_checked_inside_schedule_expansion():
    from calendar_audit.core import get_zone
    from calendar_audit.schedule import effective_schedule
    class Expired:
        calls = 0
        def check(self):
            self.calls += 1
            if self.calls == 4:
                raise AuditError('Execution-time limit exceeded')
    with pytest.raises(AuditError, match='Execution-time'):
        effective_schedule(validate_spec(SPEC2), get_zone('UTC'), Expired())
