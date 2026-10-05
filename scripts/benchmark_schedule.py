#!/usr/bin/env python3
"""Bounded synthetic schedule workloads, fresh-process Linux VmHWM and CLI time.

No performance improvement hypothesis: record costs and deterministic outputs.
Two fresh processes per case. Replay verifies input/output hashes and outcomes,
never historical timings. Socket access is blocked inside every worker.
"""
import argparse
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
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
SEED = 20261005
CASES = ['maximum_windows', 'split_recurring', 'dated_replacements', 'spanning', 'dst_spring', 'dst_fall', 'incomplete']


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def inputs(name):
    rng = random.Random(SEED)
    first, last, zone = '2026-01-01', '2026-04-01', 'UTC'
    weekly = {d: [['09:00', '12:00'], ['13:00', '17:00']] for d in ['MO','TU','WE','TH','FR','SA','SU']}
    exceptions, events = [], []
    if name == 'maximum_windows':
        weekly = {d: [[f'{h:02d}:00', f'{h:02d}:30'] for h in range(16)] for d in weekly}
    if name in ('split_recurring', 'dated_replacements'):
        for i in range(100):
            start = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)+timedelta(seconds=rng.randrange(10*3600))
            end = start+timedelta(minutes=5)
            events.append(f'UID:recurring-{i}\nDTSTART:{start:%Y%m%dT%H%M%SZ}\nDTEND:{end:%Y%m%dT%H%M%SZ}\nRRULE:FREQ=DAILY;COUNT=90')
    if name == 'dated_replacements':
        exceptions = [dict(date=str(date(2026,1,1)+timedelta(days=i)),
                           windows=[] if i%3==0 else [['06:00', '08:00'], ['18:00', '20:00']]) for i in range(90)]
    if name == 'spanning':
        for i in range(100):
            events.append(f'UID:span-{i}\nDTSTART:20251231T000000Z\nDTEND:20260402T000000Z')
    if name.startswith('dst_'):
        first, last = ('2026-03-07', '2026-03-10') if name == 'dst_spring' else ('2026-10-31', '2026-11-03')
        zone = 'America/New_York'
        weekly = {d: [['00:00','04:00'], ['09:00','12:00']] for d in weekly}
        events = ['UID:transparent\nDTSTART:'+first.replace('-','')+'T140000Z\nTRANSP:TRANSPARENT']
    if name == 'incomplete':
        events = ['UID:unsupported\nDTSTART:20260101T100000Z\nRRULE:FREQ=MONTHLY']
    spec = dict(version=2, start=first, end=last, timezone=zone, weekly=weekly,
                exceptions=exceptions, minimum_seconds=1800, all_day='block')
    source = 'BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Synthetic schedule measurements//EN\n'+''.join(
        'BEGIN:VEVENT\n'+event+'\nEND:VEVENT\n' for event in events)+'END:VCALENDAR\n'
    return source.encode(), (json.dumps(spec, sort_keys=True)+'\n').encode()


def worker(args):
    import socket
    def denied(*args, **kwargs):
        os.write(2, b'Unexpected network access\n')
        os._exit(97)
    socket.socket = socket.create_connection = socket.getaddrinfo = denied
    from benchmark_index import worker as measured_cli
    return measured_cli(args)


def stable(run):
    return {k: v for k, v in run.items() if k not in (
        'elapsed_seconds', 'peak_rss_kib', 'availability_seconds', 'analysis_seconds')}


def measure(output, replay=None):
    from calendar_audit.core import Limits
    assert platform.system() == 'Linux', 'VmHWM measurements require Linux'
    assert not output.exists(), 'Choose a new output filename'
    saved = json.loads(replay.read_text()) if replay else None
    source_paths = sorted((ROOT/'src/calendar_audit').glob('*.py')) + [Path(__file__), ROOT/'scripts/benchmark_index.py']
    result = dict(schema_version=1, measured_at_utc=datetime.now(timezone.utc).isoformat(), seed=SEED,
                  method=__doc__, python=platform.python_version(), platform=platform.platform(),
                  dependencies={n: metadata.version(n) for n in ('icalendar','tzdata','python-dateutil','six')},
                  limits=asdict(Limits()), repetitions=2,
                  implementation_sha256={str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in source_paths}, workloads=[])
    for index, name in enumerate(CASES):
        raw, specification = inputs(name)
        case = dict(name=name, input_sha256={'synthetic.ics': digest(raw), 'working.json': digest(specification)},
                    input_bytes=len(raw), schedule_bytes=len(specification), spec=json.loads(specification), runs=[])
        with tempfile.TemporaryDirectory(prefix='schedule-measure-') as temp:
            base = Path(temp)
            source, schedule = base/'synthetic.ics', base/'working.json'
            source.write_bytes(raw)
            schedule.write_bytes(specification)
            for repetition in range(2):
                destination, metrics = base/f'report-{repetition}', base/f'metrics-{repetition}.json'
                command = [sys.executable, str(Path(__file__).resolve()), '--worker', str(metrics),
                           str(source), '--spec', str(schedule), '--output', str(destination)]
                started = time.perf_counter()
                proc = subprocess.run(command, cwd=base, capture_output=True, text=True, timeout=40,
                    env={**os.environ, 'PYTHONPATH':str(ROOT/'src'), 'PYTHONNOUSERSITE':'1'})
                elapsed = time.perf_counter()-started
                assert proc.returncode == (2 if name == 'incomplete' else 0), proc.stderr
                measurement = json.loads(metrics.read_text())
                assert Path(measurement.pop('import_origin')).resolve() == ROOT/'src/calendar_audit/availability.py'
                report = json.loads((destination/'report.json').read_text())
                observation = dict(exit_code=proc.returncode, elapsed_seconds=elapsed, **measurement,
                    complete=report['complete'], working_seconds=report['working_seconds'],
                    occupied_seconds=report['occupied_seconds'], candidate_seconds=report['candidate_seconds'],
                    windows=len(report['windows']), candidates=len(report['candidates']),
                    output_bytes={p.name:p.stat().st_size for p in sorted(destination.iterdir())},
                    output_sha256={p.name:digest(p.read_bytes()) for p in sorted(destination.iterdir())})
                assert source.read_bytes() == raw and schedule.read_bytes() == specification
                assert max(observation['output_bytes'].values()) <= Limits().report_bytes
                assert observation['peak_rss_kib'] > 0 and observation['elapsed_seconds'] > 0
                case['runs'].append(observation)
            assert stable(case['runs'][0]) == stable(case['runs'][1])
        if saved:
            previous = saved['workloads'][index]
            assert previous['name'] == name and previous['input_sha256'] == case['input_sha256']
            assert stable(previous['runs'][0]) == stable(case['runs'][0])
        result['workloads'].append(case)
        print(f'{name}: {case["runs"][0]["elapsed_seconds"]:.3f}s; '
              f'{case["runs"][0]["peak_rss_kib"]} KiB; {case["runs"][0]["windows"]} windows', flush=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        return worker(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--replay', type=Path)
    args = parser.parse_args()
    measure(args.output, args.replay)
    return 0


if __name__ == '__main__':
    sys.exit(main())
