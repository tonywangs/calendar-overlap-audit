#!/usr/bin/env python3
"""Reproduce the frozen index experiment with fresh Linux CLI processes.

End-to-end includes interpreter startup, parsing, availability and bundle writes.
Availability-stage timing wraps availability() and subtracts analyze() time; it
includes spec/window validation, selection, complements, provenance and result
construction, but excludes parsing/expansion, serialization and disk writes.
Peak RSS is /proc/self/status VmHWM, not inherited pre-exec getrusage maxrss.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time

from index_experiment import ROOT, SNAPSHOT, CANDIDATE, SUITE, digest, materialize


def inputs(case, seed):
    rng = random.Random(seed)
    base = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
    events = []
    for i in range(case['events']):
        kind = case['kind']
        if kind == 'all_day':
            bounds = 'DTSTART;VALUE=DATE:20260101\nDTEND;VALUE=DATE:20260401'
            rule = ''
        else:
            start = base + timedelta(seconds=i*360+rng.randrange(30) if kind == 'sparse' else 0)
            if kind == 'spanning':
                start -= timedelta(days=rng.randrange(3))
            end = start + timedelta(seconds=60 if kind == 'sparse' else 3600)
            if kind == 'spanning':
                end = base + timedelta(days=case['days'], hours=rng.randrange(3))
            bounds = f'DTSTART:{start:%Y%m%dT%H%M%SZ}\nDTEND:{end:%Y%m%dT%H%M%SZ}'
            rule = f'\nRRULE:FREQ=DAILY;COUNT={case["days"]}' if kind in ('sparse','dense') else ''
        events.append(f'BEGIN:VEVENT\nUID:{i}\n{bounds}{rule}\nEND:VEVENT\n')
    return ('BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Frozen index experiment//EN\n'+''.join(events)+'END:VCALENDAR\n').encode()


def specification(case):
    return dict(version=1,start='2026-01-01',end=(datetime(2026,1,1)+timedelta(days=case['days'])).date().isoformat(),
        timezone='UTC',weekdays=['MO','TU','WE','TH','FR','SA','SU'],work_start='09:00',work_end='17:00',minimum_seconds=1,all_day='block')


def worker(argv):
    import importlib
    module = importlib.import_module('calendar_audit.availability')
    cli = importlib.import_module('calendar_audit.availability_cli')
    analyzed = 0.0
    stage = 0.0
    def analyzer(fn):
        def measured(*args, **kwargs):
            nonlocal analyzed
            started = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                analyzed += time.perf_counter()-started
        return measured
    module.analyze = analyzer(module.analyze)
    module.analyze_occurrences = analyzer(module.analyze_occurrences)
    original = cli.availability
    def measured(*args, **kwargs):
        nonlocal stage
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            stage = time.perf_counter()-started-analyzed
    cli.availability = measured
    metrics, *args = argv
    code = cli.main(args)
    status = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines())
    peak, unit = status['VmHWM'].split()
    assert unit == 'kB'
    Path(metrics).write_text(json.dumps(dict(peak_rss_kib=int(peak),availability_seconds=stage,
        analysis_seconds=analyzed,import_origin=module.__file__)))
    return code


def stable(run):
    return {k:v for k,v in run.items() if k not in ('implementation','repetition','position',
        'elapsed_seconds','availability_seconds','analysis_seconds','peak_rss_kib')}


def evaluate(result):
    gates = result['suite']['gates']
    rows = []
    for workload in result['workloads']:
        stats = {}
        for implementation in ('baseline','candidate'):
            runs = [r for r in workload['runs'] if r['implementation'] == implementation]
            stats[implementation] = {k:statistics.median(r[k] for r in runs) for k in
                ('elapsed_seconds','availability_seconds','analysis_seconds')}
            stats[implementation]['peak_rss_kib'] = max(r['peak_rss_kib'] for r in runs)
        a,b = stats['baseline'],stats['candidate']
        delta = b['elapsed_seconds']-a['elapsed_seconds']
        rss = b['peak_rss_kib']-a['peak_rss_kib']
        target = workload['name'] in gates['required_targets']
        rows.append(dict(name=workload['name'],statistics=stats,
            improvement=1-b['elapsed_seconds']/a['elapsed_seconds'],
            target_pass=(not target or b['elapsed_seconds'] <= a['elapsed_seconds']*(1-gates['minimum_end_to_end_improvement'])),
            control_pass=(target or not (delta > gates['control_regression_seconds'] and delta/a['elapsed_seconds'] > gates['control_regression_fraction'])),
            rss_pass=not (rss > gates['rss_regression_kib'] and rss/a['peak_rss_kib'] > gates['rss_regression_fraction']),
            exact_outputs=all(stable(r)==stable(workload['runs'][0]) for r in workload['runs'])))
    return dict(workloads=rows,performance_and_output_gates_pass=all(all(row[k] for k in
        ('target_pass','control_pass','rss_pass','exact_outputs')) for row in rows))


def run_suite(output, replay=None):
    assert platform.system() == 'Linux', 'Fresh-process VmHWM measurement requires Linux'
    suite = json.loads(SUITE.read_text())
    repeats = 1 if replay else suite['repetitions']
    from calendar_audit.core import Limits
    from dataclasses import asdict
    result = dict(schema_version=1,measured_at_utc=datetime.now(timezone.utc).isoformat(),method=__doc__,
        suite=suite,suite_sha256=digest(SUITE),baseline_sha256=digest(SNAPSHOT),candidate_sha256=digest(CANDIDATE),
        script_sha256={p.name:digest(p) for p in (Path(__file__),ROOT/'scripts/index_experiment.py')},
        python=platform.python_version(),platform=platform.platform(),
        dependencies={n:metadata.version(n) for n in ('icalendar','tzdata','python-dateutil','six')},
        limits=asdict(Limits()),repeats=repeats,workloads=[])
    if replay:
        for key in ('suite_sha256','baseline_sha256','candidate_sha256','script_sha256','dependencies','limits'):
            assert result[key] == replay[key], key
    suite_start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='index-benchmark-') as temp:
        base = Path(temp)
        sources = {name:materialize(base/name,name=='candidate') for name in ('baseline','candidate')}
        for index,case in enumerate(suite['workloads']):
            source = base/(case['name']+'.ics')
            spec = base/'working.json'
            source.write_bytes(inputs(case,suite['seed']+index))
            spec.write_text(json.dumps(specification(case),sort_keys=True)+'\n')
            before = {p.name:digest(p) for p in (source,spec)}
            record = dict(name=case['name'],seed=suite['seed']+index,input_sha256=before,spec=specification(case),runs=[])
            for repetition in range(repeats):
                order = ['baseline','candidate'] if repetition%2==0 else ['candidate','baseline']
                for position,implementation in enumerate(order):
                    assert time.monotonic()-suite_start < suite['suite_timeout_seconds']
                    out = base/f'{index}-{repetition}-{implementation}'
                    metrics = base/'metrics.json'
                    env = {**os.environ,'PYTHONPATH':str(sources[implementation]),'PYTHONNOUSERSITE':'1'}
                    cmd = [sys.executable,str(Path(__file__).resolve()),'--worker',str(metrics),str(source),
                        '--spec',str(spec),'--output',str(out)]
                    start = time.perf_counter()
                    process = subprocess.run(cmd,cwd=base,env=env,capture_output=True,timeout=suite['process_timeout_seconds'])
                    elapsed = time.perf_counter()-start
                    assert process.returncode == 0, process.stderr.decode()+process.stdout.decode()
                    measurement = json.loads(metrics.read_text())
                    assert measurement.pop('import_origin').startswith(str(sources[implementation]))
                    report = json.loads((out/'report.json').read_text())
                    assert report['complete']
                    record['runs'].append(dict(implementation=implementation,repetition=repetition,position=position,
                        elapsed_seconds=elapsed,**measurement,exit_code=process.returncode,complete=report['complete'],
                        candidate_seconds=report['candidate_seconds'],occurrences=len(report['audit']['occurrences']),
                        output_sha256={p.name:digest(p) for p in sorted(out.iterdir())},
                        output_bytes={p.name:p.stat().st_size for p in sorted(out.iterdir())}))
                    assert before == {p.name:digest(p) for p in (source,spec)}
                    assert not list(base.glob('.calendar-audit-*'))
            assert all(stable(r)==stable(record['runs'][0]) for r in record['runs']),case['name']
            if replay:
                expected = replay['workloads'][index]
                assert record['input_sha256'] == expected['input_sha256']
                assert stable(record['runs'][0]) == stable(expected['runs'][0]),case['name']
            # Independent analytic occupancy: each sparse event is 60 seconds,
            # dense events cover one hour daily, spanning/all-day fill the window.
            occupied = case['events']*60*case['days'] if case['kind']=='sparse' else case['days']*(3600 if case['kind']=='dense' else 8*3600)
            assert record['runs'][0]['candidate_seconds'] == case['days']*8*3600-occupied
            result['workloads'].append(record)
            for impl in ('baseline','candidate'):
                runs = [r for r in record['runs'] if r['implementation']==impl]
                print(f"{case['name']} {impl}: E2E {statistics.median(r['elapsed_seconds'] for r in runs):.4f}s; stage {statistics.median(r['availability_seconds'] for r in runs):.4f}s",flush=True)
    result['evaluation'] = evaluate(result)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')


def main():
    if sys.argv[1:2] == ['--worker']:
        return worker(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--replay',type=Path)
    args = parser.parse_args()
    run_suite(args.output,json.loads(args.replay.read_text()) if args.replay else None)
    return 0


if __name__ == '__main__':
    sys.exit(main())
