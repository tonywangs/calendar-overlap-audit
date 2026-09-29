from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import random

import pytest

from calendar_audit.core import AuditError, Budget, Limits, analyze, overlap_pairs, union_seconds
from calendar_audit.report import json_bytes
from conftest import FIXTURES


def audit(paths, start='2026-03-01', end='2026-03-20', zone='UTC', **kwargs):
    return analyze(paths, start, end, zone, **kwargs)


def uid_occurrences(report, uid):
    ids = {e['id'] for e in report['events'] if e['uid'] == uid}
    return [o for o in report['occurrences'] if o['event'] in ids]


def test_synthetic_core_use_case():
    path = FIXTURES / 'synthetic.ics'
    r = audit([path], '2026-03-06', '2026-03-11', 'America/New_York')
    assert r['complete'] and r['occupied_seconds'] == 23400
    assert len(r['overlaps']) == 3
    assert sorted(p['seconds'] for p in r['overlaps']) == [600, 600, 1800]
    assert len(r['occurrences']) == 11
    assert [d['occupied_seconds'] for d in r['daily']] == [12600, 3600, 0, 3600, 3600]
    assert [d['all_day_occurrences'] for d in r['daily']] == [1, 1, 0, 0, 0]
    assert r['sources'][0]['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert json_bytes(r) == json_bytes(audit([path], '2026-03-06', '2026-03-11', 'America/New_York'))
    assert b'PRIVATE_' not in json_bytes(r)


def test_spring_gap_and_exact_elapsed_duration():
    r = audit([FIXTURES / 'dst-spring.ics'], '2026-03-07', '2026-03-12', 'America/New_York')
    assert r['complete']
    assert [o['start'] for o in uid_occurrences(r, 'gap-series')] == [
        '2026-03-07T07:30:00Z', '2026-03-09T06:30:00Z', '2026-03-10T06:30:00Z', '2026-03-11T06:30:00Z']
    exact = uid_occurrences(r, 'fixed-elapsed')
    assert [(o['start'], o['end']) for o in exact] == [
        ('2026-03-08T04:00:00Z', '2026-03-08T08:00:00Z'),
        ('2026-03-09T03:00:00Z', '2026-03-09T07:00:00Z')]
    assert [d['day_seconds'] for d in r['daily']] == [86400, 82800, 86400, 86400, 86400]
    assert [d['all_day_occurrences'] for d in r['daily']] == [1, 1, 1, 0, 0]
    assert sum(d['occupied_seconds'] for d in r['daily']) == r['occupied_seconds']


def test_fall_first_fold_and_duration():
    r = audit([FIXTURES / 'dst-fall.ics'], '2026-10-31', '2026-11-03', 'America/New_York')
    assert r['complete']
    assert [o['start'] for o in uid_occurrences(r, 'fold-series')] == [
        '2026-10-31T05:30:00Z', '2026-11-01T05:30:00Z', '2026-11-02T06:30:00Z']
    explicit = uid_occurrences(r, 'fold-explicit')[0]
    assert explicit['start'] == '2026-11-01T05:30:00Z'
    assert explicit['end'] == '2026-11-01T07:30:00Z'
    assert r['daily'][1]['day_seconds'] == 90000
    assert r['occupied_seconds'] == 14400


def test_weekly_interval_week_start_until_and_exdates():
    r = audit([FIXTURES / 'weekly.ics'], end='2026-04-01')
    assert r['complete']
    assert [o['start'][:10] for o in uid_occurrences(r, 'weekly-interval')] == ['2026-03-01', '2026-03-17', '2026-03-29']
    assert [o['start'][:10] for o in uid_occurrences(r, 'weekly-until')] == ['2026-03-02', '2026-03-09', '2026-03-16']


def test_clipping_exact_boundaries_nested_and_simultaneous(make_ics):
    p = make_ics(
        'UID:long\nDTSTART:20260228T230000Z\nDTEND:20260303T020000Z',
        'UID:one\nDTSTART:20260301T000000Z\nDTEND:20260301T010000Z',
        'UID:two\nDTSTART:20260301T000000Z\nDTEND:20260301T003000Z',
        'UID:before\nDTSTART:20260228T230000Z\nDTEND:20260301T000000Z',
        'UID:after\nDTSTART:20260302T000000Z\nDTEND:20260302T010000Z')
    r = audit([p], end='2026-03-02')
    assert r['occupied_seconds'] == 86400
    assert len(r['overlaps']) == 3 and len(r['occurrences']) == 3
    assert r['occurrences'][0]['clipped_start'] == '2026-03-01T00:00:00Z'
    assert r['occurrences'][0]['clipped_end'] == '2026-03-02T00:00:00Z'


def test_floating_default_duration_and_gap(make_ics):
    p = make_ics('UID:f\nDTSTART:20260308T023000\nDTEND:20260308T040000',
                 'UID:d\nDTSTART;VALUE=DATE:20260308', 'UID:z\nDTSTART:20260308T050000')
    r = audit([p], '2026-03-08', '2026-03-09', 'America/New_York')
    assert r['complete'] and r['occupied_seconds'] == 1800
    assert r['occurrences'][0]['start'] == '2026-03-08T07:30:00Z'
    assert r['occurrences'][1]['end'] == '2026-03-09'
    assert r['occurrences'][2]['start'] == r['occurrences'][2]['end']
    assert r['events'][0]['time_basis'] == 'floating'


@pytest.mark.parametrize('rule,dt,ex,expected', [
    ('FREQ=DAILY;UNTIL=20260303', ';VALUE=DATE:20260301', ';VALUE=DATE:20260302', ['2026-03-01','2026-03-03']),
    ('FREQ=DAILY;UNTIL=20260303T100000', ':20260301T100000', ':20260302T100000', ['2026-03-01','2026-03-03']),
    ('FREQ=DAILY;COUNT=3', ':20260301T100000Z', ':20260301T100000Z', ['2026-03-02','2026-03-03']),
    ('FREQ=DAILY;INTERVAL=2', ':20260301T100000Z', ':20260303T100000Z', ['2026-03-01','2026-03-05']),
])
def test_recurrence_types(make_ics, rule, dt, ex, expected):
    p = make_ics(f'UID:r\nDTSTART{dt}\nRRULE:{rule}\nEXDATE{ex}')
    r = audit([p], end='2026-03-06')
    assert r['complete']
    assert [o['start'][:10] for o in r['occurrences']] == expected


def test_deduplicate_across_sources_and_ambiguous_group(make_ics):
    e = 'UID:same\nSUMMARY:Shared\nDTSTART:20260301T100000Z\nDTEND:20260301T110000Z'
    a = make_ics(e, name='a.ics')
    b = make_ics(e, name='b.ics')
    r = audit([a, b])
    assert r['complete'] and len(r['occurrences']) == 1 and r['occupied_seconds'] == 3600
    assert len(r['events'][0]['sources']) == 2
    assert r['events'][1]['duplicate_of'] == 'e1'
    b.write_text(b.read_text().replace('SUMMARY:Shared', 'SUMMARY:Changed'))
    r = audit([a, b])
    assert not r['complete'] and not r['occurrences']
    assert all(e['disposition'] == 'ambiguous' for e in r['events'])


def test_single_instance_cancellation_preserves_other_instances(make_ics):
    p = make_ics('UID:same\nDTSTART:20260301T100000Z\nRRULE:FREQ=DAILY;COUNT=4',
                 'UID:same\nRECURRENCE-ID:20260302T100000Z\nSTATUS:CANCELLED')
    r = audit([p])
    assert r['complete'] and len(r['occurrences']) == 3
    assert [o['start'][:10] for o in r['occurrences']] == ['2026-03-01', '2026-03-03', '2026-03-04']
    assert len(r['cancellations']) == 1


@pytest.mark.parametrize('extra', [
    'RRULE:FREQ=SECONDLY;COUNT=999999999', 'RRULE:FREQ=MONTHLY',
    'RRULE:FREQ=DAILY;BYHOUR=1', 'RRULE:FREQ=WEEKLY;BYDAY=1MO',
    'RRULE:FREQ=DAILY;COUNT=2;UNTIL=20260310T100000Z',
    'RRULE:FREQ=DAILY;INTERVAL=0', 'RRULE:FREQ=DAILY;COUNT=-1',
    'RRULE:FREQ=DAILY;COUNT=2;COUNT=3', 'RRULE:FREQ=DAILY;UNTIL=20260310T100000',
    'RRULE:FREQ=WEEKLY;WKST=XX', 'RRULE:FREQ=WEEKLY;BYDAY=MO',
    'RDATE:20260303T100000Z', 'EXRULE:FREQ=DAILY', 'DURATION:PT1H',
    'DTSTART:20260302T100000Z', 'DTEND;VALUE=DATE:20260302',
    'DTEND:20260301T090000Z', 'EXDATE;VALUE=DATE:20260301',
    'TRANSP:UNKNOWN', 'STATUS:UNKNOWN',
])
def test_unsupported_semantics_are_incomplete(make_ics, extra):
    p = make_ics('UID:bad\nDTSTART:20260301T100000Z\n' + extra)
    r = audit([p])
    assert not r['complete'] and not r['occurrences'] and r['issues']


@pytest.mark.parametrize('raw', [
    b'not a calendar', b'BEGIN:VCALENDAR\nVERSION:2.0\n', b'\xff',
    b'BEGIN:VCALENDAR\nVERSION:2.0\nEND:VEVENT',
    b'BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\nBEGIN:VCALENDAR\nEND:VCALENDAR',
])
def test_malformed_file_preserves_hash(tmp_path, raw):
    p = tmp_path / 'bad.ics'
    p.write_bytes(raw)
    r = audit([p])
    assert not r['complete'] and r['sources'][0]['sha256'] == hashlib.sha256(raw).hexdigest()


def test_unknown_timezone_and_embedded_definition(make_ics):
    p = make_ics('UID:bad\nDTSTART;TZID=Mars/Base:20260301T100000')
    assert not audit([p])['complete']
    p.write_text(p.read_text().replace('Mars/Base', 'UTC').replace('END:VCALENDAR',
        'BEGIN:VTIMEZONE\nTZID:UTC\nEND:VTIMEZONE\nEND:VCALENDAR'))
    r = audit([p])
    assert not r['complete'] and len(r['occurrences']) == 1


def test_folded_utf8_text_and_omitted_metadata(make_ics):
    p = make_ics('UID:folded\nSUMMARY:Café\\, one\\nnext\n line\nDTSTART:20260301T100000Z\nDESCRIPTION:SECRET')
    r = audit([p])
    assert r['complete'] and r['events'][0]['summary'] == 'Café, one\nnextline'
    assert 'SECRET' not in str(r)


def test_limits(make_ics):
    p = make_ics('UID:a\nDTSTART:20260301T100000Z\nDTEND:20260301T110000Z\nRRULE:FREQ=DAILY',
                 'UID:b\nDTSTART:20260301T100000Z\nDTEND:20260301T110000Z',
                 'UID:c\nDTSTART:20260301T100000Z\nDTEND:20260301T110000Z')
    for key, value in [('input_bytes', 1), ('events', 1), ('candidates', 1), ('occurrences', 1), ('pairs', 1), ('line_bytes', 10), ('seconds', 1e-12)]:
        with pytest.raises(AuditError, match='limit'):
            audit([p], limits=replace(Limits(), **{key: value}))
    with pytest.raises(AuditError, match='files'):
        audit([p, p], limits=replace(Limits(), files=1))


@pytest.mark.parametrize('start,end', [('2026-03-01','2026-03-01'), ('2026-03-02','2026-03-01'), ('2026-01-01','2026-05-01'), ('20260301','2026-03-02')])
def test_bad_window(make_ics, start, end):
    with pytest.raises(AuditError):
        audit([make_ics()], start, end)


def test_independent_exhaustive_oracle_400_seeded_cases():
    # Unit cells, not a sweep/merge algorithm: exhaustive membership over a small
    # discrete time axis. Every generated endpoint is integral, so this is exact.
    for seed in range(400):
        rng = random.Random(seed)
        intervals = []
        for i in range(rng.randrange(0, 35)):
            a = rng.randrange(-10, 50)
            b = a + rng.randrange(0, 35)
            intervals.append((a, b, str(i)))
        occupied_cells = {t for t in range(-10, 85) if any(a <= t < b for a, b, _ in intervals)}
        expected = {}
        for i, (a, b, ident) in enumerate(intervals):
            for c, d, other in intervals[i+1:]:
                cells = [t for t in range(-10, 85) if a <= t < b and c <= t < d]
                if cells:
                    expected[frozenset((ident, other))] = len(cells)
        actual = {frozenset((left, right)): b-a for left, right, a, b in overlap_pairs(intervals, Budget(Limits()))}
        assert actual == expected, seed
        assert union_seconds((a, b) for a, b, _ in intervals) == len(occupied_cells), seed


def test_fold_exclusion_by_utc_instant_and_date_recurrence(make_ics):
    p = make_ics('UID:fold\nDTSTART;TZID=America/New_York:20261031T013000\n'
                 'DTEND;TZID=America/New_York:20261031T023000\nRRULE:FREQ=DAILY;COUNT=3\nEXDATE:20261101T053000Z',
                 'UID:dates\nDTSTART;VALUE=DATE:20261031\nDTEND;VALUE=DATE:20261102\nRRULE:FREQ=DAILY;COUNT=2')
    r = audit([p], '2026-10-31', '2026-11-04', 'America/New_York')
    assert r['complete']
    assert len(uid_occurrences(r, 'fold')) == 2
    assert [(o['start'], o['end']) for o in uid_occurrences(r, 'dates')] == [('2026-10-31', '2026-11-02'), ('2026-11-01', '2026-11-03')]
    assert r['occupied_seconds'] == 7200
    assert [d['all_day_occurrences'] for d in r['daily']] == [1, 2, 1, 0]


def test_daily_summaries_split_midnight_and_zero_length(make_ics):
    p = make_ics('UID:overnight\nDTSTART:20260301T233000Z\nDTEND:20260302T013000Z',
                 'UID:zero\nDTSTART:20260302T120000Z')
    r = audit([p], end='2026-03-03')
    assert [d['occupied_seconds'] for d in r['daily']] == [1800, 5400]
    assert [d['timed_occurrences'] for d in r['daily']] == [1, 2]


def test_unknown_zone_and_extreme_window():
    with pytest.raises(ValueError, match='timezone'):
        audit([], zone='../secret')
    with pytest.raises(AuditError, match='representable'):
        audit([], start='0001-01-01', end='0001-01-02', zone='Asia/Tokyo')


@pytest.mark.parametrize('key,value', [('events', 10**1000), ('seconds', float('inf')), ('seconds', float('nan')), ('files', 0)])
def test_limits_cannot_exceed_hard_ceilings(key, value):
    with pytest.raises(AuditError):
        replace(Limits(), **{key: value})


def test_each_overlap_and_occurrence_has_valid_citations():
    r = audit([FIXTURES / 'synthetic.ics'], '2026-03-06', '2026-03-11', 'America/New_York')
    events = {e['id'] for e in r['events']}
    sources = {s['id'] for s in r['sources']}
    occurrences = {o['id'] for o in r['occurrences']}
    assert all(o['event'] in events for o in r['occurrences'])
    assert all(s['source'] in sources and s['event'] > 0 for e in r['events'] for s in e['sources'])
    assert all(p['left'] in occurrences and p['right'] in occurrences for p in r['overlaps'])


def test_220_seeded_ics_to_report_cases_against_cell_oracle(make_ics):
    origin = datetime(2026, 3, 1, tzinfo=timezone.utc)
    for seed in range(220):
        rng = random.Random(10000 + seed)
        intervals, definitions = [], []
        for i in range(rng.randrange(0, 15)):
            start = rng.randrange(-5, 53)
            end = start + rng.randrange(0, 15)
            uid = f'synthetic-{i}'
            intervals.append((start, end, uid))
            begin = (origin + timedelta(minutes=30 * start)).strftime('%Y%m%dT%H%M%SZ')
            finish = (origin + timedelta(minutes=30 * end)).strftime('%Y%m%dT%H%M%SZ')
            definitions.append(f'UID:{uid}\nDTSTART:{begin}' + (f'\nDTEND:{finish}' if end > start else ''))
        r = audit([make_ics(*definitions)], end='2026-03-02')
        assert r['complete'], seed
        occupied = {cell for cell in range(48) if any(a <= cell < b for a, b, _ in intervals)}
        expected_pairs = {}
        for i, (a, b, uid) in enumerate(intervals):
            for c, d, other in intervals[i+1:]:
                common = {cell for cell in range(48) if a <= cell < b and c <= cell < d}
                if common:
                    expected_pairs[frozenset((uid, other))] = len(common) * 1800
        event_uids = {e['id']: e['uid'] for e in r['events']}
        occurrence_uids = {o['id']: event_uids[o['event']] for o in r['occurrences']}
        actual_pairs = {frozenset((occurrence_uids[p['left']], occurrence_uids[p['right']])): p['seconds'] for p in r['overlaps']}
        assert actual_pairs == expected_pairs, seed
        assert r['occupied_seconds'] == len(occupied) * 1800, seed
        assert r['daily'][0]['occupied_seconds'] == len(occupied) * 1800, seed
