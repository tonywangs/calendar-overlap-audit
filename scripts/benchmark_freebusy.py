#!/usr/bin/env python3
"""Bounded synthetic free/busy measurements, independent oracles and hash replay."""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from freebusy_cases import (CREATED, UID, calendar, case, event, instant, oracle,
                            read_export, stamp)

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['empty', 'sparse_1000', 'dense_2000', 'recurring_40x90', 'spring', 'fall',
         'interval_limit', 'occurrence_limit', 'output_limit', 'incomplete']


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def inputs(name):
    """Inputs and oracle expectations, independent of production expansion."""
    lo, hi = instant('2026-01-01T00:00:00Z'), instant('2026-04-01T00:00:00Z')
    start, end, zone, policy, flags = '2026-01-01', '2026-04-01', 'UTC', 'ignore', []
    intervals, events = [], []
    code = 0
    if name in ('spring', 'fall'):
        raws, start, end, lo, hi, expected = case(554505 if name == 'fall' else 554510, 'block')
        return raws, start, end, 'America/New_York', 'block', [], lo, hi, expected, 0
    if name in ('sparse_1000', 'interval_limit', 'output_limit'):
        for i in range(1000):
            a = lo + timedelta(minutes=3*i)
            b = a+timedelta(minutes=1)
            events.append(event(str(i), f'DTSTART:{stamp(a)}\nDTEND:{stamp(b)}'))
            intervals.append((a,b))
        if name != 'sparse_1000':
            flags = ['--max-intervals','10'] if name == 'interval_limit' else ['--max-report-bytes','50']
            code = 2
    elif name == 'dense_2000':
        a,b = lo+timedelta(hours=1),lo+timedelta(hours=2)
        events = [event(str(i), f'DTSTART:{stamp(a)}\nDTEND:{stamp(b)}') for i in range(2000)]
        intervals = [(a,b)]
    elif name in ('recurring_40x90', 'occurrence_limit'):
        for i in range(40):
            a = lo+timedelta(hours=9, seconds=i)
            events.append(event(str(i), f'DTSTART:{stamp(a)}\nDTEND:{stamp(a+timedelta(hours=1))}\nRRULE:FREQ=DAILY;COUNT=90'))
            intervals += [(a+timedelta(days=d), a+timedelta(days=d,hours=1)) for d in range(90)]
        if name == 'occurrence_limit':
            flags,code = ['--max-occurrences','100'],2
    elif name == 'incomplete':
        events = [event('unsupported', 'DTSTART:20260101T090000Z\nRRULE:FREQ=MONTHLY')]
        code = 2
    return [calendar(events)], start,end,zone,policy,flags,lo,hi,oracle(intervals,lo,hi),code


def worker(argv):
    # Hard failure even if the application attempts to catch a network error.
    import socket
    def denied(*args, **kwargs):
        os._exit(97)
    socket.socket = socket.create_connection = socket.getaddrinfo = denied
    from calendar_audit.freebusy_cli import main
    started = time.monotonic()
    code = main(argv[1:])
    elapsed = time.monotonic()-started
    rss = next(int(line.split()[1]) for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmHWM:'))
    Path(argv[0]).write_text(json.dumps({'exit_code':code, 'cli_seconds':elapsed, 'peak_rss_kib':rss}))


def implementation_hashes():
    paths = list((ROOT/'src/calendar_audit').glob('*.py')) + [ROOT/'pyproject.toml',
            Path(__file__), ROOT/'scripts/freebusy_cases.py']
    return {str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted(paths)}


def stable(run):
    return {key:run[key] for key in ('exit_code','output_sha256','output_bytes','periods','occupied_seconds')}


def measure():
    from calendar_audit.core import Limits
    result = {'schema_version':1, 'measured_at_utc':datetime.now(timezone.utc).isoformat(),
              'method':'Two fresh offline processes per workload. Linux VmHWM; parent elapsed includes startup. Synthetic endpoint-cell oracle. No performance improvement claim.',
              'python':platform.python_version(), 'platform':platform.platform(),
              'dependencies':{name:version(name) for name in ('icalendar','tzdata','python-dateutil','six')},
              'implementation_sha256':implementation_hashes(), 'limits':asdict(Limits()),
              'max_intervals':20000, 'repetitions':2, 'workloads':[]}
    with tempfile.TemporaryDirectory(prefix='freebusy-measure-') as temp:
        base = Path(temp)
        for name in NAMES:
            raws,start,end,zone,policy,flags,lo,hi,expected,code = inputs(name)
            paths=[]
            for index,raw in enumerate(raws):
                path=base/f'{name}-{index}.ics'; path.write_bytes(raw); paths.append(path)
            hashes={p.name:digest(p.read_bytes()) for p in paths}
            record={'name':name, 'input_sha256':hashes, 'input_bytes':sum(map(len,raws)),
                    'start':start,'end':end,'timezone':zone,'all_day':policy,'flags':flags,'runs':[]}
            for rep in range(2):
                output=base/f'{name}-{rep}'
                metrics=base/f'{name}-{rep}.json'
                args=[*map(str,paths),'--start',start,'--end',end,'--timezone',zone,'--all-day',policy,
                      '--uid',UID,'--created-at',CREATED,'--output',str(output),*flags]
                started=time.monotonic()
                proc=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(metrics),*args],
                                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=40)
                elapsed=time.monotonic()-started
                assert proc.returncode == 0, proc.stderr.decode()
                run=json.loads(metrics.read_text())
                run['elapsed_seconds']=elapsed
                assert run['exit_code'] == code, proc.stderr.decode()
                assert hashes == {p.name:digest(p.read_bytes()) for p in paths}
                raw=(output/'busy.ics').read_bytes() if output.exists() else None
                run.update(output_sha256=None,output_bytes=0,periods=None,occupied_seconds=None)
                if code == 0:
                    assert raw is not None
                    periods=read_export(raw,lo,hi,expected)
                    run.update(output_sha256=digest(raw),output_bytes=len(raw),periods=len(periods),
                               occupied_seconds=int(sum((b-a).total_seconds() for a,b in periods)))
                else:
                    assert raw is None
                assert not list(base.glob('.calendar-audit-*'))
                assert 0 < run['cli_seconds'] < elapsed and run['peak_rss_kib'] > 0
                record['runs'].append(run)
            assert stable(record['runs'][0]) == stable(record['runs'][1])
            result['workloads'].append(record)
            print(f"{name}: exit {code}; {record['runs'][0]['elapsed_seconds']:.3f}s; {record['runs'][0]['peak_rss_kib']} KiB; {record['runs'][0]['output_bytes']} bytes",flush=True)
    return result


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        worker(sys.argv[2:]); return
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--replay',type=Path)
    args=p.parse_args()
    assert not args.output.exists(), 'Choose a new evidence path'
    result=measure()
    if args.replay:
        saved=json.loads(args.replay.read_text())
        for key in ('implementation_sha256','dependencies','limits','max_intervals','repetitions'):
            assert result[key] == saved[key],key
        assert [w['name'] for w in saved['workloads']] == NAMES
        for actual,old in zip(result['workloads'],saved['workloads']):
            assert {k:v for k,v in actual.items() if k!='runs'} == {k:v for k,v in old.items() if k!='runs'}
            assert all(stable(r)==stable(old['runs'][0]) for r in actual['runs']+old['runs'])
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')


if __name__=='__main__':
    main()
