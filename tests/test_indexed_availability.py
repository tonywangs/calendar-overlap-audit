"""Exact frozen-baseline comparison and independent endpoint/provenance oracle."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from index_experiment import load_availability
from test_availability import SPEC, timed, stamp


@pytest.fixture(scope='session')
def index_modules(tmp_path_factory):
    return [load_availability(tmp_path_factory.mktemp(name), candidate)
            for name, candidate in [('index-baseline', False), ('index-candidate', True)]]


def oracle(lo, hi, busy, minimum):
    """Elementary segments, no interval-index or production merge code."""
    clipped = [(max(a, lo), min(b, hi), ident) for a,b,ident in busy if max(a,lo) < min(b,hi)]
    points = sorted({lo,hi,*[x for a,b,_ in clipped for x in (a,b)]})
    blocks, gaps = [], []
    for a,b in zip(points,points[1:]):
        occupied = any(x <= a and b <= y for x,y,_ in clipped)
        target = blocks if occupied else gaps
        if target and target[-1][1] == a:
            target[-1] = (target[-1][0],b)
        else:
            target.append((a,b))
    return ([dict(a=a,b=b,members=sorted(i for x,y,i in clipped if a <= x < y <= b),
                  left=sorted(i for x,y,i in clipped if x == a),
                  right=sorted(i for x,y,i in clipped if y == b)) for a,b in blocks],
            [(a,b,sorted(i for x,y,i in clipped if y == a) if a > lo else [],
              sorted(i for x,y,i in clipped if x == b) if b < hi else [])
             for a,b in gaps if (b-a).total_seconds() >= minimum])


def check_report(report):
    expected_gaps = []
    for window in report['windows']:
        lo,hi = [datetime.fromisoformat(window[k]) for k in ('start','end')]
        busy = []
        for o in report['audit']['occurrences']:
            if o['all_day']:
                if report['spec']['all_day']=='block' and o['start'] <= window['date'] < o['end']:
                    busy.append((lo,hi,o['id']))
            else:
                busy.append((datetime.fromisoformat(o['start']),datetime.fromisoformat(o['end']),o['id']))
        blocks,gaps = oracle(lo,hi,busy,report['spec']['minimum_seconds'])
        assert len(blocks) == len(window['busy'])
        for expected,actual in zip(blocks,window['busy']):
            assert datetime.fromisoformat(actual['start']) == expected['a']
            assert datetime.fromisoformat(actual['end']) == expected['b']
            assert actual['occurrences'] == expected['members']
            assert actual['start_occurrences'] == expected['left']
            assert actual['end_occurrences'] == expected['right']
        expected_gaps.extend((window['id'],*gap) for gap in gaps)
    if report['complete']:
        assert [(g['window'],datetime.fromisoformat(g['start']),datetime.fromisoformat(g['end']),
                 g['before'],g['after']) for g in report['candidates']] == expected_gaps
        assert report['candidate_seconds'] == sum(int((b-a).total_seconds()) for _,a,b,_,_ in expected_gaps)
    else:
        assert report['candidates'] == [] and report['candidate_seconds'] is None


@pytest.mark.parametrize('seed', range(256))
def test_exact_seeded_multiday_reports(seed, make_ics, index_modules):
    baseline,candidate = index_modules
    rng = random.Random(20261002+seed)
    start = ['2026-03-07','2026-10-31','2026-01-01','2026-03-06'][seed%4]
    first = date.fromisoformat(start)
    end = first+timedelta(days=3)
    spec = {**SPEC,'start':start,'end':end.isoformat(),'timezone':'America/New_York' if seed%4<2 else 'UTC',
            'work_start':'00:00','work_end':'04:00','all_day':'block' if seed%2 else 'ignore',
            'minimum_seconds':rng.choice([1,60,900,1800,20000])}
    lo = datetime.combine(first,datetime.min.time(),tzinfo=timezone.utc)
    events = []
    # Ties, nested and adjacent intervals, multi-day spans, and exact endpoints.
    for i in range(rng.randrange(8,28)):
        a = rng.choice([0,3600,7200,86400,90000,rng.randrange(-86400,3*86400)])
        b = a+rng.choice([0,60,3600,7200,2*86400])
        extra = rng.choice(['','','','TRANSP:TRANSPARENT','STATUS:CANCELLED'])
        events.append(timed(str(i),lo+timedelta(seconds=a),lo+timedelta(seconds=b),extra))
    rng.shuffle(events)
    # Keep master/override family in a single source; move, cancel or make transparent.
    original = lo+timedelta(hours=2)
    events.append(timed('series',original,original+timedelta(minutes=30),'RRULE:FREQ=DAILY;COUNT=3'))
    recurrence = original+timedelta(days=1)
    change = ['STATUS:CANCELLED',f'DTSTART:{stamp(recurrence+timedelta(hours=1))}',
              f'DTSTART:{stamp(recurrence)}\nTRANSP:TRANSPARENT'][seed%3]
    events.append(f'UID:series\nRECURRENCE-ID:{stamp(recurrence)}\n{change}')
    events.append(f'UID:days\nDTSTART;VALUE=DATE:{first:%Y%m%d}\nDTEND;VALUE=DATE:{end:%Y%m%d}')
    if seed%17==0:
        events.append(timed('unsupported',lo,lo+timedelta(hours=1),'RRULE:FREQ=MONTHLY'))
    paths = [make_ics(*events[:4],name='a.ics'),make_ics(*events[4:],name='b.ics')]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    for legacy in (False,True):
        a = baseline.availability(paths,spec,include_overlaps=legacy)
        b = candidate.availability(paths,spec,include_overlaps=legacy)
        assert a == b
        assert json.dumps(a,sort_keys=True) == json.dumps(b,sort_keys=True)
        check_report(b)
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]


@pytest.mark.parametrize('seed', range(32))
def test_split_window_index_and_provenance(seed,index_modules):
    _,module = index_modules
    rng = random.Random(seed)
    lo = datetime(2026,3,6,tzinfo=timezone.utc)
    working = [(lo.date(),lo+timedelta(hours=a),lo+timedelta(hours=b)) for a,b in [(0,4),(5,8),(8,9),(12,17)]]
    raw = [(lo+timedelta(seconds=a),lo+timedelta(seconds=b),str(i)) for i,(a,b) in enumerate(
        [(0,0),(0,3600),(3600,14400),(14400,18000),(-86400,3*86400),(28800,32400)]+
        [(a,a+rng.randrange(0,86400)) for a in [rng.randrange(-86400,86400) for _ in range(40)]])]
    occurrences = [dict(start=a.isoformat(),end=b.isoformat(),id=i,all_day=False) for a,b,i in raw]
    occurrences += [dict(start='2026-03-06',end='2026-03-07',id='day',all_day=True)]
    for policy in ('block','ignore'):
        selected = module.indexed_busy(working,occurrences,policy,module.Budget(module.Limits()))
        for (_,a,b),items in zip(working,selected):
            expected_busy = raw+([(a,b,'day')] if policy=='block' else [])
            actual = list(items)
            assert actual == sorted(item for item in expected_busy if max(item[0],a)<min(item[1],b))
            blocks,gaps = module.complement(a,b,actual,60,module.Budget(module.Limits()),presorted=True)
            for block in blocks:
                for key in ('members','left','right'):
                    block[key].sort()
            gaps = [(x,y,sorted(left),sorted(right)) for x,y,left,right in gaps]
            assert (blocks,gaps) == oracle(a,b,expected_busy,60)


@pytest.mark.parametrize('all_day', [False, True])
def test_index_checks_deadline_during_bucket_fanout(index_modules, all_day):
    _,module = index_modules
    lo = datetime(2026,1,1,tzinfo=timezone.utc)
    working = [((lo+timedelta(days=i)).date(),lo+timedelta(days=i),lo+timedelta(days=i+1)) for i in range(90)]
    occurrences = [dict(start=lo.date().isoformat() if all_day else lo.isoformat(),
        end=(lo+timedelta(days=90)).date().isoformat() if all_day else (lo+timedelta(days=90)).isoformat(),
        id='span',all_day=all_day)]
    class Expired:
        checks = 0
        def check(self):
            self.checks += 1
            if self.checks == 20:
                raise module.AuditError('Execution-time limit exceeded')
    with pytest.raises(module.AuditError,match='Execution-time'):
        list(module.indexed_busy(working,occurrences,'block',Expired()))


@pytest.mark.parametrize('failure', ['deadline','sigint','sigterm'])
def test_cli_failure_during_index_construction(tmp_path, monkeypatch, failure):
    import importlib
    import os
    import signal
    from calendar_audit.availability_cli import main
    from test_availability_cli import arguments
    module = importlib.import_module('calendar_audit.availability')
    argv = arguments(tmp_path)
    before = {p:Path(p).read_bytes() for p in (argv[0],argv[2])}
    original = module.indexed_busy
    def interrupted(*args, **kwargs):
        # Failure occurs while consuming the lazy index, after expansion.
        for bucket in original(*args, **kwargs):
            if failure == 'deadline':
                raise module.AuditError('Execution-time limit exceeded')
            os.kill(os.getpid(),signal.SIGINT if failure=='sigint' else signal.SIGTERM)
            yield bucket
    monkeypatch.setattr(module,'indexed_busy',interrupted)
    assert main(argv) == (2 if failure=='deadline' else 130)
    assert not (tmp_path/'out').exists() and not list(tmp_path.glob('.calendar-audit-*'))
    assert before == {p:Path(p).read_bytes() for p in before}
