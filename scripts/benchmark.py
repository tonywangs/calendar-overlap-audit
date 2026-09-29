#!/usr/bin/env python3
"""Generate bounded synthetic workloads and measure real CLI child processes.

Linux wait4 records each child's peak RSS, not a parent/cumulative peak. Seeded
inputs are regenerated instead of publishing large or private calendar fixtures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260928
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def stamp(value):
    return f'{value.year:04d}{value.month:02d}{value.day:02d}T{value.hour:02d}{value.minute:02d}{value.second:02d}Z'


def event(uid, start, duration=30, rule=None):
    return '\n'.join(['BEGIN:VEVENT', f'UID:synthetic-{uid}', f'SUMMARY:Synthetic workload {uid}',
        f'DTSTART:{stamp(start)}', f'DTEND:{stamp(start + timedelta(seconds=duration))}',
        *([f'RRULE:{rule}'] if rule else []), 'END:VEVENT'])


def workloads():
    rng = random.Random(SEED)
    return {
        'sparse_3000': ([event(i, BASE + timedelta(minutes=i)) for i in range(3000)], 0, 90000, 0),
        'seeded_500': ([event(i, BASE + timedelta(minutes=rng.randrange(90 * 1440)), duration=rng.randrange(1, 31)*60)
                        for i in range(500)], 0, None, None),
        'dense_180': ([event(i, BASE, 3600) for i in range(180)], 0, 3600, 16110),
        'daily_100_by_90': ([event(i, BASE + timedelta(minutes=i), rule='FREQ=DAILY;COUNT=90') for i in range(100)], 0, 270000, 0),
        'dense_pair_limit_250': ([event(i, BASE, 3600) for i in range(250)], 1, None, None),
        'ancient_candidate_limit': ([event('ancient', datetime(1, 1, 1, tzinfo=timezone.utc), rule='FREQ=DAILY')], 1, None, None),
    }


def override(uid, original, moved=None):
    return '\n'.join(['BEGIN:VEVENT', f'UID:synthetic-{uid}', f'RECURRENCE-ID:{stamp(original)}',
        *([f'DTSTART:{stamp(moved)}'] if moved is not None else ['STATUS:CANCELLED']), 'END:VEVENT'])


def override_workloads():
    series = []
    dense = []
    for i in range(100):
        start = BASE + timedelta(minutes=i)
        series.extend([event(i,start,rule='FREQ=DAILY;COUNT=90'),
                       override(i,start+timedelta(days=45)),
                       override(i,start+timedelta(days=89),start+timedelta(days=1,seconds=30))])
        dense.extend([event(i,start,rule='FREQ=DAILY;COUNT=2'),override(i,start,BASE)])
    return {
        'overrides_100_by_90': (series, 0, 267000, 0),
        'overrides_dense_100': (dense, 0, 3030, 4950),
        'override_resolution_limit': ([event('ancient',datetime(1,1,1,tzinfo=timezone.utc),rule='FREQ=DAILY'),
                                      override('ancient',BASE)], 2, 0, 0),
        'override_orphan': ([event('orphan',BASE,rule='FREQ=DAILY;COUNT=2'),
                             override('orphan',BASE+timedelta(days=5))], 2, 0, 0),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--suite', choices=['baseline', 'overrides', 'all'], default='baseline')
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error('--repeats must be 1..10')
    if platform.system() != 'Linux':
        parser.error('Linux required for documented ru_maxrss units (KiB)')
    results = {'schema_version': 1, 'seed': SEED, 'repeats': args.repeats,
               'measured_at_utc': datetime.now(timezone.utc).isoformat(),
               'platform': platform.platform(), 'python': platform.python_version(),
               'implementation_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                          for p in sorted((ROOT / 'src/calendar_audit').glob('*.py'))},
               'benchmark_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'dependencies': {name: metadata.version(name) for name in ('calendar-overlap-audit', 'icalendar', 'tzdata', 'python-dateutil', 'six')},
               'method': 'Fresh CLI process per repetition; perf_counter elapsed seconds; Linux wait4 ru_maxrss KiB; default resource limits; no warmup.',
               'workloads': []}
    with tempfile.TemporaryDirectory(prefix='calendar-benchmark-') as temp:
        base = Path(temp)
        cases = {}
        if args.suite in ('baseline', 'all'):
            cases.update(workloads())
        if args.suite in ('overrides', 'all'):
            cases.update(override_workloads())
        for name, (events, expected_exit, expected_seconds, expected_pairs) in cases.items():
            source = base / (name + '.ics')
            raw = ('BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Synthetic benchmark//EN\n' + '\n'.join(events) + '\nEND:VCALENDAR\n').encode()
            source.write_bytes(raw)
            record = {'name': name, 'input_bytes': len(raw), 'input_sha256': hashlib.sha256(raw).hexdigest(),
                      'input_events': len(events), 'runs': []}
            for repeat in range(args.repeats):
                output = base / f'{name}-{repeat}'
                command = [sys.executable, '-m', 'calendar_audit', str(source), '--start', '2026-01-01',
                           '--end', '2026-04-01', '--timezone', 'UTC', '--output', str(output)]
                started = time.perf_counter()
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
                _, status, usage = os.wait4(process.pid, 0)
                elapsed = time.perf_counter() - started
                process.returncode = os.waitstatus_to_exitcode(status)
                stdout, stderr = process.communicate()
                assert process.returncode == expected_exit, (name, process.returncode, stderr)
                measurement = {'elapsed_seconds': elapsed, 'peak_rss_kib': usage.ru_maxrss, 'exit_code': process.returncode}
                if process.returncode in (0, 2):
                    report = json.loads((output / 'report.json').read_text())
                    assert report['complete'] == (process.returncode == 0)
                    if process.returncode == 2:
                        expected_code = 'resolution_limit' if name.endswith('limit') else 'orphan_override'
                        assert {i['code'] for i in report['issues']} == {expected_code}
                        measurement['issue_codes'] = [expected_code]
                    if expected_seconds is not None:
                        assert report['occupied_seconds'] == expected_seconds
                    if expected_pairs is not None:
                        assert len(report['overlaps']) == expected_pairs
                    measurement.update(occupied_seconds=report['occupied_seconds'], overlap_pairs=len(report['overlaps']),
                                       occurrences=len(report['occurrences']),
                                       output_bytes={p.name: p.stat().st_size for p in output.iterdir()},
                                       output_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()})
                else:
                    assert not output.exists()
                    measurement['failure'] = stderr.decode().strip()
                    expected_reason = 'pairs limit exceeded' if name.startswith('dense') else 'candidates limit exceeded'
                    assert expected_reason in measurement['failure']
                assert hashlib.sha256(source.read_bytes()).hexdigest() == record['input_sha256']
                assert not list(base.glob('.calendar-audit-*'))
                record['runs'].append(measurement)
            results['workloads'].append(record)
            print(f'{name}: exit {expected_exit}; {record["runs"][-1]["elapsed_seconds"]:.3f}s; {record["runs"][-1]["peak_rss_kib"]} KiB', flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
