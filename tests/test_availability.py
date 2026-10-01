"""Independent occupancy-lattice oracle, temporal policy and provenance checks."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import hashlib
import json
import random

import pytest

from calendar_audit.availability import availability, boundary, load_spec, validate_spec
from calendar_audit.availability_report import html_bytes
from calendar_audit.core import AuditError, Budget, Limits, get_zone
from calendar_audit.report import json_bytes
from conftest import FIXTURES

SPEC = dict(version=1, start='2026-03-06', end='2026-03-07', timezone='UTC',
            weekdays=['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'], work_start='09:00',
            work_end='17:00', minimum_seconds=1800, all_day='block')
UTC = timezone.utc


def stamp(value):
    return value.strftime('%Y%m%dT%H%M%SZ')


def timed(uid, start, end, extra=''):
    return f'UID:{uid}\nDTSTART:{stamp(start)}\nDTEND:{stamp(end)}\n{extra}'


def test_union_adjacency_endpoint_citations_and_exact_minimum(make_ics):
    p = make_ics('UID:a\nDTSTART:20260306T090000Z\nDTEND:20260306T100000Z',
                 'UID:b\nDTSTART:20260306T093000Z\nDTEND:20260306T110000Z',
                 'UID:c\nDTSTART:20260306T110000Z\nDTEND:20260306T120000Z',
                 'UID:d\nDTSTART:20260306T110000Z\nDTEND:20260306T120000Z',
                 'UID:e\nDTSTART:20260306T123000Z\nDTEND:20260306T170000Z')
    r = availability([p], SPEC)
    assert r['complete'] and len(r['candidates']) == 1
    g = r['candidates'][0]
    assert (g['start'], g['end'], g['seconds']) == ('2026-03-06T12:00:00Z', '2026-03-06T12:30:00Z', 1800)
    assert g['before'] == ['o3', 'o4'] and g['after'] == ['o5']
    assert r['windows'][0]['busy'][0]['occurrences'] == ['o1', 'o2', 'o3', 'o4']
    assert not availability([p], {**SPEC, 'minimum_seconds': 1801})['candidates']


# These UTC endpoints are explicit expected civil-time conversions, not computed
# with the implementation's timezone resolver. Three/five-hour DST windows and
# a fractional-offset zone exercise elapsed-time subtraction.
SCENARIOS = [
    ('2026-03-06', '2026-03-07', 'UTC', '2026-03-06T00:00:00+00:00', 14400),
    ('2026-03-08', '2026-03-09', 'America/New_York', '2026-03-08T05:00:00+00:00', 10800),
    ('2026-11-01', '2026-11-02', 'America/New_York', '2026-11-01T04:00:00+00:00', 18000),
    ('2026-03-06', '2026-03-07', 'Asia/Kathmandu', '2026-03-05T18:15:00+00:00', 14400),
]


@pytest.mark.parametrize('seed', range(256))
def test_seeded_independent_second_lattice_oracle(seed, make_ics, baseline_availability):
    rng = random.Random(20260930 + seed)
    start, end, zone, utc, length = SCENARIOS[seed % len(SCENARIOS)]
    lo = datetime.fromisoformat(utc)
    minimum = rng.choice([1, 60, 900, 1800, length, length + 1])
    policy = 'block' if seed % 2 else 'ignore'
    busy = [False] * length
    events = []
    for i in range(rng.randrange(0, 20)):
        a = rng.randrange(-3600, length + 3601)
        b = a + rng.randrange(0, 7201)
        mode = rng.randrange(6)
        extra = 'TRANSP:TRANSPARENT' if mode == 1 else ('STATUS:CANCELLED' if mode == 2 else '')
        events.append(timed(str(i), lo + timedelta(seconds=a), lo + timedelta(seconds=b), extra))
        left, right = max(0, a), min(length, b)
        if not extra and left < right:
            busy[left:right] = [True] * (right - left)
    if seed % 9 == 0:
        events.append(f'UID:day\nDTSTART;VALUE=DATE:{start.replace("-", "")}\nDTEND;VALUE=DATE:{end.replace("-", "")}')
        if policy == 'block':
            busy = [True] * length
    # Moved or cancelled recurrence instance on the only day of interest.
    if seed % 5 == 0:
        original = lo + timedelta(seconds=600)
        events.append(timed('series', original, original + timedelta(seconds=300), 'RRULE:FREQ=DAILY;COUNT=2'))
        moved = lo + timedelta(seconds=2400)
        change = 'STATUS:CANCELLED' if seed % 10 == 0 else f'DTSTART:{stamp(moved)}'
        events.append(f'UID:series\nRECURRENCE-ID:{stamp(original)}\n{change}')
        if seed % 10:
            busy[2400:2700] = [True] * 300
    # Oracle enumerates each second, discovering runs from occupancy transitions;
    # no sorting/merging, production complement or recurrence expansion is used.
    expected = []
    cursor = None
    for i, occupied in enumerate(busy + [True]):
        if not occupied and cursor is None:
            cursor = i
        if occupied and cursor is not None:
            if i - cursor >= minimum:
                expected.append((lo + timedelta(seconds=cursor), lo + timedelta(seconds=i)))
            cursor = None
    p = make_ics(*events)
    spec = {**SPEC, 'start': start, 'end': end, 'timezone': zone,
            'work_start': '00:00', 'work_end': '04:00', 'minimum_seconds': minimum, 'all_day': policy}
    r = availability([p], spec)
    assert r['complete']
    from baseline import semantics
    baseline = baseline_availability([p], spec)
    assert baseline['complete']
    assert semantics(r) == semantics(baseline)
    assert availability([p], spec, include_overlaps=True) == baseline
    got = [(datetime.fromisoformat(g['start']), datetime.fromisoformat(g['end'])) for g in r['candidates']]
    assert got == expected
    assert r['windows'][0]['seconds'] == length
    assert r['candidate_seconds'] == sum(int((b-a).total_seconds()) for a,b in expected)


@pytest.mark.parametrize('day,hour,kind', [('2026-03-08','02:30','Nonexistent'), ('2026-11-01','01:30','Ambiguous')])
@pytest.mark.parametrize('which', ['work_start', 'work_end'])
def test_dst_boundaries_rejected(make_ics, day, hour, kind, which):
    end = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    spec = {**SPEC, 'start': day, 'end': end, 'timezone': 'America/New_York', 'work_start': '00:00', 'work_end': '04:00', which: hour}
    with pytest.raises(AuditError, match=kind + ' boundary.*change working hours'):
        availability([make_ics()], spec)


def test_skipped_date_query_boundary_rejected(make_ics):
    with pytest.raises(AuditError, match='Nonexistent boundary'):
        availability([make_ics()], {**SPEC, 'start':'2011-12-30', 'end':'2011-12-31', 'timezone':'Pacific/Apia'})


def test_midnight_crossing_all_day_and_weekdays(make_ics):
    p = make_ics('UID:night\nDTSTART:20260305T230000Z\nDTEND:20260306T003000Z',
                 'UID:days\nDTSTART;VALUE=DATE:20260306\nDTEND;VALUE=DATE:20260308')
    spec = {**SPEC, 'end': '2026-03-09', 'work_start':'00:00', 'work_end':'24:00', 'weekdays':['SU','FR']}
    blocked = availability([p], spec)
    assert len(blocked['windows']) == 2 and blocked['spec']['weekdays'] == ['FR','SU']
    assert [g['date'] for g in blocked['candidates']] == ['2026-03-08']
    ignored = availability([p], {**spec, 'all_day':'ignore'})
    assert [g['seconds'] for g in ignored['candidates']] == [84600, 86400]
    assert ignored['candidates'][0]['start'] == '2026-03-06T00:30:00Z'
    assert ignored['candidates'][1]['end'] == '2026-03-09T00:00:00Z'


def test_empty_and_fully_occupied(make_ics):
    empty = availability([make_ics()], SPEC)
    assert empty['candidate_seconds'] == 28800
    assert empty['candidates'][0]['before'] == empty['candidates'][0]['after'] == []
    full = availability([make_ics('UID:all\nDTSTART:20260305T000000Z\nDTEND:20260308T000000Z')], SPEC)
    assert full['complete'] and full['candidate_seconds'] == 0 and not full['candidates']
    no_days = availability([make_ics()], {**SPEC, 'weekdays':['MO']})
    assert no_days['complete'] and not no_days['windows'] and not no_days['candidates']


def test_override_and_snapshot_boundaries(make_ics):
    spec = {**SPEC, 'start':'2026-03-03', 'end':'2026-03-06'}
    r = availability([FIXTURES / 'overrides.ics'], spec)
    assert r['complete'] and r['audit']['cancellations']
    assert sum(w['seconds'] for w in r['windows']) - r['candidate_seconds'] == 9000
    p = make_ics('UID:series\nDTSTART:20260306T090000Z\nDTEND:20260306T100000Z\nRRULE:FREQ=DAILY;COUNT=2', name='master.ics')
    q = make_ics('UID:series\nRECURRENCE-ID:20260306T090000Z\nSTATUS:CANCELLED', name='detached.ics')
    r = availability([p, q], SPEC)
    assert not r['complete'] and r['candidate_seconds'] is None and not r['candidates']
    assert any(i['code'] == 'conflicting_snapshots' for i in r['audit']['issues'])
    duplicate = availability([p, p], SPEC)
    assert duplicate['complete'] and len(duplicate['windows'][0]['busy']) == 1
    assert len(duplicate['audit']['events'][0]['sources']) == 2


@pytest.mark.parametrize('event', [
    'UID:unsupported\nDTSTART:20260306T090000Z\nRRULE:FREQ=MONTHLY',
    'UID:orphan\nRECURRENCE-ID:20260306T090000Z\nSTATUS:CANCELLED',
    'UID:unknown\nDTSTART;TZID=Unknown/Zone:20260306T090000',
])
def test_incomplete_withholds_all_candidates(make_ics, event):
    r = availability([make_ics(event)], SPEC)
    assert not r['complete'] and not r['candidates'] and r['candidate_seconds'] is None
    page = html_bytes(r, Budget(Limits()))
    assert b'candidate intervals withheld' in page and b'data-gap ' not in page


def test_resolution_limit_incomplete(make_ics):
    p = make_ics('UID:series\nDTSTART:20260306T090000Z\nRRULE:FREQ=DAILY;COUNT=3',
                 'UID:series\nRECURRENCE-ID:20260308T090000Z\nSTATUS:CANCELLED')
    r = availability([p], SPEC, limits=replace(Limits(), resolutions=1))
    assert not r['complete'] and not r['candidates']


@pytest.mark.parametrize('key,value', [
    ('version',True), ('version',2), ('minimum_seconds',False), ('minimum_seconds',0),
    ('minimum_seconds',1.1), ('minimum_seconds',7776001), ('weekdays',[]), ('weekdays',['FR','FR']),
    ('weekdays',['fr']), ('weekdays',[{}]), ('timezone',None), ('timezone','/UTC'), ('timezone','Unknown/Zone'),
    ('all_day','default'), ('work_start','9:00'), ('work_start','24:00'), ('work_end','09:00'),
    ('work_end','25:00'), ('work_end','12:60'), ('start','2026-3-6'), ('end','2026-03-06'),
    ('end','2026-07-01'), ('start',False),
])
def test_malformed_specs(key, value):
    with pytest.raises((AuditError, ValueError)):
        validate_spec({**SPEC, key:value})


@pytest.mark.parametrize('change', ['extra','missing','list'])
def test_exact_spec_keys(change):
    data = {**SPEC, 'unexpected':1} if change == 'extra' else ({k:v for k,v in SPEC.items() if k != 'all_day'} if change == 'missing' else [])
    with pytest.raises(AuditError):
        validate_spec(data)


@pytest.mark.parametrize('raw', [b'{"version":1,"version":1}', b'{', b'\xff', b' ' * 16385, b'[' * 2000])
def test_invalid_spec_file(tmp_path, raw):
    p = tmp_path / 'spec.json'
    p.write_bytes(raw)
    with pytest.raises(AuditError):
        load_spec(p)


def test_deterministic_reports_input_fingerprints_and_offsets(make_ics, tmp_path):
    p = make_ics('UID:hostile\nSUMMARY:<img src=https://invalid.test/x onerror=window.pwned=1>\nDTSTART:20260306T100000Z\nDTEND:20260306T110000Z')
    specfile = tmp_path / 'spec.json'
    specfile.write_text(json.dumps(SPEC))
    spec, fingerprint = load_spec(specfile)
    before = [hashlib.sha256(x.read_bytes()).hexdigest() for x in (p, specfile)]
    a, b = [availability([p], spec, spec_source=fingerprint) for _ in range(2)]
    assert json_bytes(a) == json_bytes(b)
    assert html_bytes(a, Budget(Limits())) == html_bytes(b, Budget(Limits()))
    assert b'<img ' not in html_bytes(a, Budget(Limits()))
    assert a['audit']['sources'][0]['sha256'] == before[0]
    assert a['spec_source']['sha256'] == before[1]
    assert before == [hashlib.sha256(x.read_bytes()).hexdigest() for x in (p, specfile)]
    r = availability([make_ics()], {**SPEC, 'start':'2026-11-01', 'end':'2026-11-02', 'timezone':'America/New_York', 'work_start':'00:00', 'work_end':'04:00'})
    g = r['candidates'][0]
    assert g['seconds'] == 18000 and g['local_start'].endswith('-04:00') and g['local_end'].endswith('-05:00')
