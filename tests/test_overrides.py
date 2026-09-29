"""Synthetic override fixtures; independent materialized-occurrence oracle."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from importlib import resources
import random
from zoneinfo import ZoneInfo

import pytest

from calendar_audit.core import Limits, analyze
from calendar_audit.report import json_bytes

UTC = timezone.utc
MASTER = 'UID:s\nSUMMARY:Master\nDTSTART:20260301T100000Z\nDTEND:20260301T110000Z\nRRULE:FREQ=DAILY;COUNT=10'


def audit(path, **kwargs):
    return analyze([path], '2026-03-03', '2026-03-06', 'UTC', **kwargs)


def test_moves_across_both_window_edges_and_cancellation(make_ics):
    p = make_ics(MASTER,
        'UID:s\nRECURRENCE-ID:20260301T100000Z\nDTSTART:20260303T090000Z',
        'UID:s\nRECURRENCE-ID:20260310T100000Z\nDTSTART:20260303T093000Z\nDTEND:20260303T113000Z',
        'UID:s\nRECURRENCE-ID:20260303T100000Z\nDTSTART:20260320T100000Z',
        'UID:s\nRECURRENCE-ID:20260304T100000Z\nSTATUS:CANCELLED',
        'UID:s\nRECURRENCE-ID:20260305T100000Z\nDTSTART:20260305T100000Z\nTRANSP:TRANSPARENT')
    r = audit(p)
    assert r['complete'] and len(r['occurrences']) == 2
    assert r['occupied_seconds'] == 9000
    assert [o['recurrence_id'] for o in r['occurrences']] == ['2026-03-01T10:00:00Z', '2026-03-10T10:00:00Z']
    assert len(r['overlaps']) == 1 and r['overlaps'][0]['seconds'] == 1800
    assert r['cancellations'] == [{'master':'e1', 'override':'e5', 'recurrence_id':'2026-03-04T10:00:00Z', 'reason':'STATUS:CANCELLED'}]
    assert r['events'][1]['inherited'] == ['SUMMARY', 'TRANSP', 'STATUS', 'duration']
    assert r['events'][1]['summary'] == 'Master'
    assert r['events'][1]['effective_end'] == '2026-03-03T10:00:00Z'
    assert all(o['master'] == 'e1' and o['override'] == o['event'] for o in r['occurrences'])
    assert json_bytes(r) == json_bytes(audit(p))


@pytest.mark.parametrize('exception,code', [
    ('RECURRENCE-ID:20260320T100000Z\nSTATUS:CANCELLED', 'orphan_override'),
    ('RECURRENCE-ID:20260302T110000Z\nSTATUS:CANCELLED', 'orphan_override'),
    ('RECURRENCE-ID;VALUE=DATE:20260302\nSTATUS:CANCELLED', 'incompatible_identity'),
    ('RECURRENCE-ID:20260302T100000\nSTATUS:CANCELLED', 'incompatible_identity'),
    ('RECURRENCE-ID;TZID=Europe/London:20260302T100000\nSTATUS:CANCELLED', 'incompatible_identity'),
    ('RECURRENCE-ID;TZID=Unknown/Zone:20260302T100000\nSTATUS:CANCELLED', 'unsupported_event'),
    ('RECURRENCE-ID;RANGE=THISANDFUTURE:20260302T100000Z\nSTATUS:CANCELLED', 'unsupported_range'),
    ('RECURRENCE-ID;RANGE=BOGUS:20260302T100000Z\nSTATUS:CANCELLED', 'unsupported_range'),
    ('RECURRENCE-ID:20260302T100000Z', 'missing_override_start'),
    ('RECURRENCE-ID:20260302T100000Z\nDTSTART;VALUE=DATE:20260302', 'incompatible_timing'),
    ('RECURRENCE-ID:20260302T100000Z\nDTSTART:20260302T100000', 'incompatible_timing'),
    ('RECURRENCE-ID:20260302T100000Z\nSTATUS:CANCELLED\nDTEND:broken', 'unsupported_event'),
    ('RECURRENCE-ID:20260302T100000Z\nSTATUS:CANCELLED\nRRULE:FREQ=DAILY', 'unsupported_override'),
    ('RECURRENCE-ID:20260302T100000Z\nSTATUS:CANCELLED\nEXDATE:20260302T100000Z', 'unsupported_override'),
    ('RECURRENCE-ID:20260302T100000Z\nSTATUS:CANCELLED\nDURATION:PT1H', 'unsupported_override'),
    ('RECURRENCE-ID:20260302T100000Z\nRECURRENCE-ID:20260303T100000Z\nSTATUS:CANCELLED', 'unsupported_event'),
])
def test_invalid_family_is_atomic(make_ics, exception, code):
    r = audit(make_ics(MASTER, 'UID:s\n' + exception,
                      'UID:independent\nDTSTART:20260303T120000Z\nDTEND:20260303T130000Z'))
    assert not r['complete'] and r['occupied_seconds'] == 3600
    assert len(r['occurrences']) == 1 and r['occurrences'][0]['event'] == 'e3'
    assert code in {i['code'] for i in r['issues']}
    assert not r['cancellations']


def test_conflicts_duplicates_and_snapshot_boundaries(make_ics):
    override = 'UID:s\nRECURRENCE-ID:20260304T100000Z\nSTATUS:CANCELLED'
    a = make_ics(MASTER, override, override, name='a.ics')
    b = make_ics(override, MASTER, name='b.ics')
    r = analyze([a,b], '2026-03-03','2026-03-06','UTC')
    assert r['complete'] and len(r['occurrences']) == 2 and len(r['cancellations']) == 1
    assert len(r['events'][0]['sources']) == 2 and len(r['events'][1]['sources']) == 3
    for components, code in [
        ([override], 'orphan_override'),
        ([MASTER, MASTER+'\nSEQUENCE:2', override], 'conflicting_masters'),
        ([MASTER, override, override+'\nSEQUENCE:2'], 'conflicting_overrides'),
        ([MASTER+'\nEXDATE:20260304T100000Z',override], 'exdate_override_collision'),
        ([MASTER+'\nSTATUS:CANCELLED',override], 'cancelled_master_with_overrides'),
        ([MASTER.replace('\nRRULE:FREQ=DAILY;COUNT=10',''),override], 'nonrecurring_master'),
    ]:
        r = audit(make_ics(*components))
        assert not r['complete'] and not r['occurrences'] and not r['cancellations']
        assert r['issues'][0]['code'] == code
    b = make_ics(MASTER, name='b.ics')
    r = analyze([a,b], '2026-03-03','2026-03-06','UTC')
    assert not r['complete'] and r['issues'][0]['code'] == 'conflicting_snapshots'
    a = make_ics(override, name='a.ics')
    r = analyze([a,b], '2026-03-03','2026-03-06','UTC')
    assert not r['complete'] and not r['occurrences']


def test_resolution_limit_is_incomplete_not_partial(make_ics):
    p = make_ics(MASTER,'UID:s\nRECURRENCE-ID:20260310T100000Z\nDTSTART:20260303T120000Z')
    r = audit(p, limits=replace(Limits(), resolutions=5))
    assert not r['complete'] and not r['occurrences']
    assert r['issues'][0]['code'] == 'resolution_limit'


def test_transparent_master_can_have_opaque_override(make_ics):
    p = make_ics(MASTER+'\nTRANSP:TRANSPARENT',
                'UID:s\nRECURRENCE-ID:20260304T100000Z\nDTSTART:20260304T100000Z\nTRANSP:OPAQUE\nSUMMARY:')
    r = audit(p)
    assert r['complete'] and r['occupied_seconds'] == 3600 and len(r['occurrences']) == 1
    assert r['events'][1]['summary'] == ''


def test_exact_boundaries_zero_duration_clipping(make_ics):
    p = make_ics(MASTER,
        'UID:s\nRECURRENCE-ID:20260303T100000Z\nDTSTART:20260302T230000Z',
        'UID:s\nRECURRENCE-ID:20260304T100000Z\nDTSTART:20260306T000000Z',
        'UID:s\nRECURRENCE-ID:20260305T100000Z\nDTSTART:20260302T233000Z')
    r = audit(p)
    assert r['complete'] and r['occupied_seconds'] == 1800 and len(r['occurrences']) == 1
    p = make_ics(MASTER.replace('\nDTEND:20260301T110000Z',''),
        'UID:s\nRECURRENCE-ID:20260304T100000Z\nDTSTART:20260303T000000Z')
    r = audit(p)
    assert r['complete'] and r['occupied_seconds'] == 0 and len(r['occurrences']) == 3


def test_gap_identity_is_not_normalized_to_another_local_time(make_ics):
    master = ('UID:s\nDTSTART;TZID=America/New_York:20260307T023000\n'
              'DTEND;TZID=America/New_York:20260307T033000\nRRULE:FREQ=DAILY;COUNT=4')
    p = make_ics(master, 'UID:s\nRECURRENCE-ID;TZID=America/New_York:20260308T023000\nSTATUS:CANCELLED')
    r = analyze([p], '2026-03-07','2026-03-12','America/New_York')
    assert not r['complete'] and r['issues'][0]['code'] == 'orphan_override'
    # Explicit gap seed is legal and can be cancelled by its original local fields.
    p = make_ics(master.replace('20260307','20260308'),
                 'UID:s\nRECURRENCE-ID;TZID=America/New_York:20260308T023000\nSTATUS:CANCELLED')
    # End at 03:30 would equal the gap seed instant; choose a valid explicit end.
    p.write_text(p.read_text().replace('20260308T033000','20260308T043000'))
    r = analyze([p], '2026-03-07','2026-03-13','America/New_York')
    assert r['complete'] and len(r['cancellations']) == 1


def _zone(name):
    with resources.files('tzdata.zoneinfo').joinpath(*name.split('/')).open('rb') as f:
        return ZoneInfo.from_file(f, key=name)


def _identity(value, kind):
    if kind == 'date':
        return value.isoformat()
    if kind == 'floating':
        return value.replace(tzinfo=None).isoformat()
    if kind == 'utc':
        return value.isoformat().replace('+00:00','Z')
    return value.isoformat()


def test_256_seeded_series_against_explicit_occurrence_oracle(make_ics):
    """No production recurrence/overlap/union helpers are used for expected values.

    Weekly originals are built from calendar-week blocks, daily originals from
    indexed dates. Independent brute-force minute cells measure occupancy, and
    quadratic interval intersection checks every pair (including same-series pairs).
    """
    for seed in range(256):
        rng = random.Random(710000 + seed)
        kind = ['utc','zoned','floating','date'][seed % 4]
        zone_name = 'UTC' if kind == 'utc' else 'America/New_York'
        tz = _zone(zone_name)
        base = datetime(2026, 3, 1, 2, 30) if seed % 8 < 4 else datetime(2026,10,25,1,30)
        if kind == 'date':
            base = base.date()
        else:
            base = base.replace(tzinfo=tz)
        first = date(2026,3,5) if seed % 8 < 4 else date(2026,10,29)
        last = first + timedelta(days=8)
        lo = datetime.combine(first, datetime.min.time(), tz).astimezone(UTC)
        hi = datetime.combine(last, datetime.min.time(), tz).astimezone(UTC)
        duration = timedelta(days=2) if kind == 'date' else timedelta(minutes=rng.choice([0,30,60,120]))
        interval = rng.choice([1,2])
        count = rng.randrange(8,18)
        weekly = seed % 3 == 0
        if weekly:
            days = sorted({base.weekday(),rng.randrange(7),rng.randrange(7)})
            wkst = rng.choice([0,6])
            week = base - timedelta(days=(base.weekday()-wkst)%7)
            candidates = sorted(week + timedelta(weeks=n*interval, days=(d-wkst)%7)
                                for n in range(count+1) for d in days)
            rule = f'FREQ=WEEKLY;INTERVAL={interval};COUNT={count};BYDAY=' + ','.join(
                ['MO','TU','WE','TH','FR','SA','SU'][d] for d in days) + ';WKST=' + ['MO','TU','WE','TH','FR','SA','SU'][wkst]
        else:
            candidates = [base + timedelta(days=n*interval) for n in range(count+3)]
            rule = f'FREQ=DAILY;INTERVAL={interval};COUNT={count}'
        originals = []
        for candidate in candidates:
            if candidate < base:
                continue
            if kind != 'date' and candidate != base:
                back = candidate.astimezone(UTC).astimezone(tz)
                if back.replace(tzinfo=None) != candidate.replace(tzinfo=None):
                    continue
            originals.append(candidate)
            if len(originals) == count:
                break
        assert len(originals) == count
        param = {'date':';VALUE=DATE', 'utc':'', 'floating':'', 'zoned':';TZID=America/New_York'}[kind]
        def prop(name, value):
            form = '%Y%m%d' if kind == 'date' else '%Y%m%dT%H%M%S' + ('Z' if kind == 'utc' else '')
            return name + param + ':' + value.strftime(form)
        # Elapsed duration for masters, even across a transition.
        end = base + duration if kind == 'date' else (base.astimezone(UTC)+duration).astimezone(tz)
        components = ['\n'.join(['UID:s', 'SUMMARY:Seed '+str(seed), prop('DTSTART',base),
                                 *([prop('DTEND',end)] if duration else []), 'RRULE:'+rule])]
        selected = set(rng.sample(range(count), min(5,count)))
        excluded = set(rng.sample([i for i in range(count) if i not in selected], 2))
        components[0] += '\n' + prop('EXDATE', originals[min(excluded)]) + '\n' + prop('EXDATE', originals[max(excluded)])
        expected, cancelled = {}, set()
        for i, original in enumerate(originals):
            start, length, transparent, cancel = original, duration, False, False
            if i in selected:
                start = original + timedelta(days=rng.randrange(-30,31))
                cancel = rng.randrange(4) == 0
                transparent = rng.randrange(5) == 0
                changed_duration = rng.randrange(2) == 0
                length = (timedelta(days=rng.randrange(1,4)) if kind == 'date'
                          else timedelta(minutes=rng.choice([30,60,180]))) if changed_duration else duration
                fields = ['UID:s', prop('RECURRENCE-ID',original)]
                if cancel:
                    fields.append('STATUS:CANCELLED')
                    cancelled.add(_identity(original,kind))
                else:
                    fields.append(prop('DTSTART',start))
                    if changed_duration:
                        finish = start + length if kind == 'date' else (start.astimezone(UTC)+length).astimezone(tz)
                        # Local serialization cannot encode fold=1; choose an
                        # unambiguous end so this is valid RFC input.
                        if kind != 'date' and finish.fold:
                            length += timedelta(hours=1)
                            finish = (start.astimezone(UTC)+length).astimezone(tz)
                        fields.append(prop('DTEND',finish))
                    if transparent:
                        fields.append('TRANSP:TRANSPARENT')
                components.append('\n'.join(fields))
            if i in excluded or cancel or transparent:
                continue
            a = start if kind == 'date' else start.astimezone(UTC)
            b = a + length
            lower, upper = (first,last) if kind == 'date' else (lo,hi)
            if max(a,lower) < min(b,upper) or (kind != 'date' and a == b and lower <= a < upper):
                expected[_identity(original,kind)] = (a,b,max(a,lower),min(b,upper))
        if seed % 5 == 0:
            components.append(components[-1])
        rng.shuffle(components)
        path = make_ics(*components)
        r = analyze([path], first.isoformat(),last.isoformat(),zone_name)
        assert r['complete'], (seed,r['issues'])
        actual = {o['recurrence_id']:o for o in r['occurrences']}
        assert set(actual) == set(expected), seed
        for identity, (a,b,c,d) in expected.items():
            assert (actual[identity]['start'],actual[identity]['end'],actual[identity]['clipped_start'],actual[identity]['clipped_end']) == tuple(
                v.isoformat().replace('+00:00','Z') for v in (a,b,c,d)), seed
        assert {c['recurrence_id'] for c in r['cancellations']} == cancelled, seed
        pairs = {}
        items = list(expected.items())
        cells = set()
        if kind != 'date':
            for i,(identity,(a,b,c,d)) in enumerate(items):
                cells.update(range(int((c-lo).total_seconds()/60),int((d-lo).total_seconds()/60)))
                for other,(_,_,x,y) in items[i+1:]:
                    seconds = int((min(d,y)-max(c,x)).total_seconds())
                    if seconds > 0:
                        pairs[frozenset((identity,other))] = seconds
        ids = {o['id']:o['recurrence_id'] for o in r['occurrences']}
        assert {frozenset((ids[p['left']],ids[p['right']])):p['seconds'] for p in r['overlaps']} == pairs, seed
        assert r['occupied_seconds'] == len(cells)*60, seed
        assert sum(d['occupied_seconds'] for d in r['daily']) == r['occupied_seconds'], seed
        if seed % 16 == 0:
            reordered = analyze([make_ics(*reversed(components))], first.isoformat(),last.isoformat(),zone_name)
            assert reordered['complete']
            assert {(o['recurrence_id'],o['start'],o['end']) for o in reordered['occurrences']} == {
                (o['recurrence_id'],o['start'],o['end']) for o in r['occurrences']}, seed
            assert reordered['occupied_seconds'] == r['occupied_seconds'], seed


def test_until_membership_and_different_effective_timezone(make_ics):
    master = MASTER.replace('COUNT=10', 'UNTIL=20260305T100000Z')
    change = 'UID:s\nRECURRENCE-ID:20260305T100000Z\nDTSTART;TZID=Asia/Tokyo:20260304T190000'
    r = audit(make_ics(master,change))
    assert r['complete'] and r['occupied_seconds'] == 7200
    assert len(r['occurrences']) == 3 and len(r['overlaps']) == 1
    assert len({o['recurrence_id'] for o in r['occurrences']}) == 3
    r = audit(make_ics(master,change.replace('RECURRENCE-ID:20260305','RECURRENCE-ID:20260306')))
    assert not r['complete'] and not r['occurrences']
    assert r['issues'][0]['code'] == 'orphan_override'


def test_malformed_exception_summary_excludes_whole_family(make_ics):
    r = audit(make_ics(MASTER, 'UID:s\nRECURRENCE-ID:20260304T100000Z\n'
                      'STATUS:CANCELLED\nSUMMARY:one\nSUMMARY:two'))
    assert not r['complete'] and not r['occurrences']
