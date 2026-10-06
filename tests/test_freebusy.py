"""Independent semantic oracle and wire-format conformance for every export."""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sys
from uuid import UUID

import pytest
from calendar_audit.core import AuditError, Budget, Limits
from calendar_audit.freebusy import (Occupancy, calendar_bytes, export_identity,
                                     fold, occupied)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from freebusy_cases import CREATED, SEEDS, UID, case, instant, read_export


@pytest.mark.parametrize('seed', SEEDS)
@pytest.mark.parametrize('policy', ['block', 'ignore'])
def test_seeded_calendar_oracle(tmp_path, seed, policy):
    raws, start, end, lo, hi, expected = case(seed, policy)
    paths = [tmp_path / f'PRIVATE-PATH-{n}.ics' for n in range(len(raws))]
    for path, raw in zip(paths, raws):
        path.write_bytes(raw)
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    result = occupied(paths, start, end, 'America/New_York', policy)
    raw = calendar_bytes(result, Budget(Limits()), uid=UID, created_at=CREATED)
    read_export(raw, lo, hi, expected)
    assert raw == calendar_bytes(occupied(list(reversed(paths)), start, end, 'America/New_York', policy),
                                 Budget(Limits()), uid=UID, created_at=CREATED)
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    assert all(h.encode() not in raw for h in before)
    assert all(str(p).encode() not in raw and p.name.encode() not in raw for p in paths)


def test_gap_fold_explicit_expectations():
    fixtures = Path(__file__).parent / 'fixtures'
    cases = [('dst-spring.ics', '2026-03-07', '2026-03-11', '2026-03-07T05:00:00Z', '2026-03-11T04:00:00Z', [
        ('2026-03-07T07:30:00Z', '2026-03-07T08:30:00Z'),
        ('2026-03-08T04:00:00Z', '2026-03-08T08:00:00Z'),
        ('2026-03-09T03:00:00Z', '2026-03-09T07:30:00Z'),
        ('2026-03-10T06:30:00Z', '2026-03-10T07:30:00Z')]),
        ('dst-fall.ics', '2026-10-31', '2026-11-03', '2026-10-31T04:00:00Z', '2026-11-03T05:00:00Z', [
        ('2026-10-31T05:30:00Z', '2026-10-31T06:30:00Z'),
        ('2026-11-01T05:30:00Z', '2026-11-01T07:30:00Z'),
        ('2026-11-02T06:30:00Z', '2026-11-02T07:30:00Z')])]
    for name, start, end, lo, hi, expected in cases:
        result = occupied([fixtures/name], start, end, 'America/New_York', 'ignore')
        raw = calendar_bytes(result, Budget(Limits()), uid=UID, created_at=CREATED)
        read_export(raw, instant(lo), instant(hi), [(instant(a), instant(b)) for a,b in expected])


@pytest.mark.parametrize('text', ['X:' + 'a'*300, 'X:' + '日é🙂'*80, 'a'*75, 'a'*76, ''])
def test_octet_folding(text):
    raw = fold(text)
    lines = raw[:-2].split(b'\r\n')
    assert all(len(line) <= 75 for line in lines)
    for line in lines:
        line.decode('utf8')
    assert all(line.startswith(b' ') for line in lines[1:])
    assert raw.replace(b'\r\n ', b'')[:-2].decode() == text


@pytest.mark.parametrize('value', ['x\nUID:injected', 'x\rUID:injected'])
def test_fold_injection(value):
    with pytest.raises(AuditError):
        fold(value)


def test_identity():
    a, stamp = export_identity()
    b, _ = export_identity()
    assert a != b and UUID(a[9:]).version == 4
    assert stamp.tzinfo == timezone.utc and not stamp.microsecond
    assert abs((datetime.now(timezone.utc)-stamp).total_seconds()) < 3
    assert export_identity(UID, CREATED) == ('urn:uuid:'+UID, instant(CREATED))


@pytest.mark.parametrize('uid', ['', 'source-event@example.com', UID.upper(), '00000000-0000-0000-0000-000000000000', UID+'\r\nURL:secret'])
def test_identity_rejects(uid):
    with pytest.raises(AuditError):
        export_identity(uid, CREATED)


@pytest.mark.parametrize('stamp', ['', '2026-01-01', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00.1Z', '2026-02-30T00:00:00Z', '2026-01-01T00:00:60Z'])
def test_creation_rejects(stamp):
    with pytest.raises(AuditError):
        export_identity(UID, stamp)


@pytest.mark.parametrize('periods', [[(1, 1)], [(2, 1)], [(-1, 2)], [(1, 11)], [(2, 3), (1, 2)], [(1, 3), (3, 4)], [(1, 4), (2, 3)]])
def test_serializer_rejects_invalid_union(periods):
    lo = instant('2026-01-01T00:00:00Z')
    result = Occupancy(lo, lo+timedelta(seconds=10), tuple((lo+timedelta(seconds=a), lo+timedelta(seconds=b)) for a,b in periods))
    with pytest.raises(AuditError):
        calendar_bytes(result, Budget(Limits()), uid=UID, created_at=CREATED)


def test_serializer_time_and_limits():
    lo = instant('2026-01-01T00:00:00Z')
    for bad in [lo.replace(tzinfo=None), lo.replace(microsecond=1)]:
        with pytest.raises(AuditError):
            calendar_bytes(Occupancy(bad, lo+timedelta(days=1), ()), Budget(Limits()))
    with pytest.raises(AuditError, match='report_bytes limit'):
        calendar_bytes(Occupancy(lo, lo+timedelta(days=1), ()), Budget(Limits(report_bytes=1)))


def test_midnight_policy(make_ics):
    empty = make_ics()
    with pytest.raises(AuditError, match='Nonexistent'):
        occupied([empty], '2011-12-30', '2012-01-01', 'Pacific/Apia', 'block')
    with pytest.raises(AuditError, match='Ambiguous'):
        occupied([empty], '2026-11-01', '2026-11-02', 'America/Havana', 'block')


def test_pairs_are_not_computed(make_ics, monkeypatch):
    import calendar_audit.core as core
    def fail(*args):
        pytest.fail('Pair enumeration is irrelevant to occupancy')
    monkeypatch.setattr(core, 'overlap_pairs', fail)
    source = make_ics(*[f'UID:{i}\nDTSTART:20260101T010000Z\nDTEND:20260101T020000Z' for i in range(50)])
    assert len(occupied([source], '2026-01-01', '2026-01-02', 'UTC', 'ignore', Limits(pairs=1)).periods) == 1
