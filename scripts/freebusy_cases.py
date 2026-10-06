"""Frozen synthetic calendars and independent endpoint-cell occupancy oracle.

No imports from calendar_audit. New York's 2026 transition offsets below are
explicit expectations, not inferred using the implementation's timezone helpers.
"""
from datetime import datetime, timedelta, timezone
import random

UTC = timezone.utc
SEEDS = range(554500, 554756)
UID = '5e603c28-3e93-4cf5-9e25-0e0e48aab378'
CREATED = '2026-10-06T01:00:00Z'
SECRET = 'PLANTED-PRIVATE-5545'


def stamp(t):
    return t.strftime('%Y%m%dT%H%M%SZ')


def instant(s):
    return datetime.fromisoformat(s)


def event(uid, fields):
    return ('BEGIN:VEVENT\nUID:' + SECRET + uid + '\nSUMMARY:' + SECRET + 'title\n'
            'DESCRIPTION:' + SECRET + 'description\nLOCATION:' + SECRET + 'location\n'
            'ATTENDEE:mailto:' + SECRET + '@example.invalid\nORGANIZER:mailto:' + SECRET + '@example.invalid\n'
            'URL:https://example.invalid/' + SECRET + '\n' + fields + '\nEND:VEVENT\n')


def calendar(events):
    return ('BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Synthetic ' + SECRET + '//EN\n' +
            ''.join(events) + 'END:VCALENDAR\n').encode()


def oracle(intervals, lo, hi):
    """Classify endpoint cells by membership; do not use a sorted merge sweep."""
    points = sorted({lo, hi} | {max(lo, min(hi, p)) for ab in intervals for p in ab})
    selected = [(a, b) for a, b in zip(points, points[1:])
                if any(x <= a and b <= y for x, y in intervals if x < y)]
    if not selected:
        return []
    starts = [a for i, (a, _) in enumerate(selected) if i == 0 or selected[i-1][1] != a]
    ends = [b for i, (_, b) in enumerate(selected) if i == len(selected)-1 or selected[i+1][0] != b]
    return list(zip(starts, ends))


def case(seed, policy):
    rng = random.Random(seed)
    fall = seed % 3 == 0
    start, end = ('2026-10-30', '2026-11-04') if fall else ('2026-03-06', '2026-03-11')
    lo = instant(start + ('T04:00:00+00:00' if fall else 'T05:00:00+00:00'))
    hi = instant(end + ('T05:00:00+00:00' if fall else 'T04:00:00+00:00'))
    left, right, expected = [], [], []
    if seed % 16 == 0:
        return [calendar([])], start, end, lo, hi, []
    # Random UTC events plus explicit clipping, adjacency, zero length and no-ops.
    if seed % 4 != 0:
        for i in range(rng.randint(4, 28)):
            a = lo + timedelta(seconds=rng.randint(-7200, int((hi-lo).total_seconds()) + 7200))
            b = a + timedelta(seconds=rng.randint(1, 9000))
            disposition = rng.choice(['', '', '', '\nTRANSP:TRANSPARENT', '\nSTATUS:CANCELLED', '\nSTATUS:TENTATIVE'])
            component = event(f'random-{i}', f'DTSTART:{stamp(a)}\nDTEND:{stamp(b)}{disposition}')
            (left if i % 2 else right).append(component)
            if disposition not in ('\nTRANSP:TRANSPARENT', '\nSTATUS:CANCELLED'):
                expected.append((a, b))
        for i, (a, b) in enumerate([(lo-timedelta(hours=1), lo+timedelta(hours=1)),
                                     (lo+timedelta(hours=1), lo+timedelta(hours=2)),
                                     (hi-timedelta(hours=1), hi+timedelta(hours=1)),
                                     (hi, hi+timedelta(hours=1)), (lo, lo)]):
            left.append(event(f'edge-{i}', f'DTSTART:{stamp(a)}' + (f'\nDTEND:{stamp(b)}' if a < b else '')))
            expected.append((a, b))
    # Daily family with EXDATE, moved into horizon from before it, cancellation,
    # and transparent override. All snapshots containing this UID are identical.
    base = datetime(2026, 10, 29) if fall else datetime(2026, 3, 5)
    local = lambda d: (base + timedelta(days=d)).strftime('%Y%m%d')
    family = [event('series', f'DTSTART;TZID=America/New_York:{local(0)}T090000\nDTEND;TZID=America/New_York:{local(0)}T093000\nRRULE:FREQ=DAILY;COUNT=8\nEXDATE;TZID=America/New_York:{local(2)}T090000'),
              event('series', f'RECURRENCE-ID;TZID=America/New_York:{local(0)}T090000\nDTSTART;TZID=America/New_York:{local(4)}T170000\nDTEND;TZID=America/New_York:{local(4)}T180000'),
              event('series', f'RECURRENCE-ID;TZID=America/New_York:{local(3)}T090000\nSTATUS:CANCELLED'),
              event('series', f'RECURRENCE-ID;TZID=America/New_York:{local(5)}T090000\nDTSTART;TZID=America/New_York:{local(5)}T090000\nDTEND;TZID=America/New_York:{local(5)}T093000\nTRANSP:TRANSPARENT')]
    left += family
    if seed % 2:
        right += family  # duplicate complete snapshot across calendars
    for d in (1, 4, 6, 7):
        hour = (13 if d < 3 else 14) if fall else (14 if d < 3 else 13)
        a = (base + timedelta(days=d, hours=hour)).replace(tzinfo=UTC)
        expected.append((a, a+timedelta(minutes=30)))
    a = (base + timedelta(days=4, hours=22 if fall else 21)).replace(tzinfo=UTC)
    expected.append((a, a+timedelta(hours=1)))
    # All-day span across DST, independently known midnight offsets.
    if seed % 5 == 0:
        da, db = ('20261031', '20261102') if fall else ('20260307', '20260309')
        right.append(event('date', f'DTSTART;VALUE=DATE:{da}\nDTEND;VALUE=DATE:{db}'))
        if policy == 'block':
            expected.append((instant('2026-10-31T04:00:00Z'), instant('2026-11-02T05:00:00Z')) if fall else
                            (instant('2026-03-07T05:00:00Z'), instant('2026-03-09T04:00:00Z')))
    # Floating nonrecurring interval, plus weekly UTC recurrence with EXDATE.
    right.append(event('floating', f'DTSTART:{local(4)}T110000\nDTEND:{local(4)}T113000'))
    a = (base + timedelta(days=4, hours=16 if fall else 15)).replace(tzinfo=UTC)
    expected.append((a, a+timedelta(minutes=30)))
    a = lo - timedelta(days=7) + timedelta(hours=3)
    left.append(event('weekly', f'DTSTART:{stamp(a)}\nDTEND:{stamp(a+timedelta(minutes=15))}\nRRULE:FREQ=WEEKLY;COUNT=3\nEXDATE:{stamp(a)}'))
    expected += [(a+timedelta(days=7*d), a+timedelta(days=7*d, minutes=15)) for d in (1, 2)]
    rng.shuffle(left)
    rng.shuffle(right)
    return [calendar(left), calendar(right)], start, end, lo, hi, oracle(expected, lo, hi)


def read_export(raw, lo, hi, expected=None):
    """Pinned reader independent of serializer; explicit conformance assertions."""
    from icalendar import Calendar
    assert raw.endswith(b'\r\n') and b'\n' not in raw.replace(b'\r\n', b'')
    assert all(len(line) <= 75 for line in raw.split(b'\r\n'))
    assert SECRET.encode() not in raw
    cal = Calendar.from_ical(raw)
    assert not cal.errors and set(cal) == {'VERSION', 'PRODID'}
    assert str(cal['VERSION']) == '2.0'
    assert len(cal.subcomponents) == 1
    fb = cal.subcomponents[0]
    assert fb.name == 'VFREEBUSY' and not fb.errors and not fb.subcomponents
    assert set(fb) <= {'UID', 'DTSTAMP', 'DTSTART', 'DTEND', 'FREEBUSY'}
    for name in ('UID', 'DTSTAMP', 'DTSTART', 'DTEND'):
        assert name in fb and not isinstance(fb[name], list)
        assert not fb[name].params
    assert str(fb['UID']) == 'urn:uuid:' + UID
    assert fb.decoded('DTSTAMP') == instant(CREATED)
    assert fb.decoded('DTSTART') == lo and fb.decoded('DTEND') == hi
    for name in ('DTSTAMP', 'DTSTART', 'DTEND'):
        assert fb[name].to_ical().endswith(b'Z')
    values = fb.get('FREEBUSY', [])
    if not isinstance(values, list):
        values = [values]
    periods = []
    for value in values:
        assert dict(value.params) == {'FBTYPE': 'BUSY'}
        a, b = value.dt
        assert isinstance(a, datetime) and isinstance(b, datetime)
        assert a.utcoffset() == b.utcoffset() == timedelta(0)
        assert lo <= a < b <= hi
        assert not periods or periods[-1][1] < a
        assert all(part.endswith(b'Z') for part in value.to_ical().split(b'/'))
        periods.append((a, b))
    if expected is not None:
        assert periods == expected
    return periods
