#!/usr/bin/env python3
"""Bounded synthetic availability workloads; actual fresh-process Linux measurements."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from benchmark import BASE, event, workloads

ROOT = Path(__file__).resolve().parents[1]
SPEC = dict(version=1, start='2026-01-01', end='2026-04-01', timezone='UTC',
            weekdays=['MO','TU','WE','TH','FR','SA','SU'], work_start='00:00',
            work_end='24:00', minimum_seconds=1, all_day='block')


def cases():
    generated = workloads()
    day = 'BEGIN:VEVENT\nUID:all-day\nDTSTART;VALUE=DATE:20260101\nDTEND;VALUE=DATE:20260401\nEND:VEVENT'
    return [
        ('empty_90_days', [], SPEC, 0, 7776000),
        ('seeded_500', generated['seeded_500'][0], SPEC, 0, None),
        ('sparse_3000', generated['sparse_3000'][0], SPEC, 0, 7686000),
        ('dense_100', [event(i,BASE,3600) for i in range(100)], SPEC, 0, 7772400),
        ('daily_40_by_90', [event(i,BASE,30,rule='FREQ=DAILY;COUNT=90') for i in range(40)], SPEC, 2, None),
        ('pair_limit_250', generated['dense_pair_limit_250'][0], SPEC, 2, None),
        ('all_day_block', [day], SPEC, 0, 0),
        ('all_day_ignore', [day], {**SPEC,'all_day':'ignore'}, 0, 7776000),
        ('dst_spring', [], {**SPEC,'start':'2026-03-08','end':'2026-03-09','timezone':'America/New_York','work_end':'04:00'}, 0, 10800),
        ('dst_fall', [], {**SPEC,'start':'2026-11-01','end':'2026-11-02','timezone':'America/New_York','work_end':'04:00'}, 0, 18000),
        ('unsupported', ['BEGIN:VEVENT\nUID:unsupported\nDTSTART:20260101T000000Z\nRRULE:FREQ=MONTHLY\nEND:VEVENT'], SPEC, 2, None),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=2)
    args = parser.parse_args()
    if platform.system() != 'Linux' or not 1 <= args.repeats <= 5:
        parser.error('Linux required; repeats must be 1..5')
    result = dict(schema_version=1, seed=20260928, repeats=args.repeats,
        measured_at_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(), platform=platform.platform(),
        method='Fresh CLI per repetition; perf_counter elapsed seconds; Linux wait4 peak child RSS in KiB; no warmup; default limits; synthetic inputs.',
        implementation_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / 'src/calendar_audit').glob('*.py'))},
        scripts_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__).resolve(), ROOT / 'scripts/benchmark.py']},
        dependencies={n:metadata.version(n) for n in ('icalendar','tzdata','python-dateutil','six')},workloads=[])
    with tempfile.TemporaryDirectory(prefix='availability-benchmark-') as temp:
        base = Path(temp)
        for name, events, spec, expected_exit, expected_seconds in cases():
            source, specpath = base / (name + '.ics'), base / 'working.json'
            source.write_text('BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Synthetic benchmark//EN\n' + '\n'.join(events) + '\nEND:VCALENDAR\n')
            specpath.write_text(json.dumps(spec,sort_keys=True) + '\n')
            hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,specpath)}
            record = dict(name=name,input_sha256=hashes,input_bytes=source.stat().st_size,input_events=len(events),spec=spec,runs=[])
            for repeat in range(args.repeats):
                output = base / f'{name}-{repeat}'
                cmd = [sys.executable,'-m','calendar_audit.availability_cli',str(source),'--spec',str(specpath),'--output',str(output)]
                started = time.perf_counter()
                process = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=ROOT)
                _, status, usage = os.wait4(process.pid,0)
                elapsed = time.perf_counter() - started
                process.returncode = os.waitstatus_to_exitcode(status)
                stdout, stderr = process.communicate()
                assert process.returncode == expected_exit, (name,stdout,stderr)
                run = dict(elapsed_seconds=elapsed,peak_rss_kib=usage.ru_maxrss,exit_code=process.returncode)
                if output.exists():
                    report = json.loads((output / 'report.json').read_text())
                    assert report['complete'] == (expected_exit == 0)
                    assert expected_seconds is None or report['candidate_seconds'] == expected_seconds
                    if not report['complete']:
                        assert not report['candidates'] and report['candidate_seconds'] is None
                    run.update(candidate_seconds=report['candidate_seconds'],candidates=len(report['candidates']),
                        output_bytes={p.name:p.stat().st_size for p in sorted(output.iterdir())},
                        output_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir())})
                else:
                    assert expected_exit == 2 and b'INCOMPLETE' in stderr
                    run['failure'] = stderr.decode().strip()
                assert hashes == {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,specpath)}
                assert not list(base.glob('.calendar-audit-*'))
                record['runs'].append(run)
            stable = [r.get('output_sha256') for r in record['runs']]
            assert all(h == stable[0] for h in stable)
            result['workloads'].append(record)
            print(f'{name}: exit {expected_exit}; {elapsed:.3f}s; {usage.ru_maxrss} KiB',flush=True)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2) + '\n')


if __name__ == '__main__':
    main()
