#!/usr/bin/env python3
"""Frozen sparse-to-dense suite: six balanced pairs of fresh CLI processes.

Replay checks exit codes, hashes and semantic digests, never timing thresholds.
The child records Linux /proc/self/status VmHWM for its current address space.
getrusage is retained separately: it can include the parent's pre-exec RSS and
is not used as the fresh-process peak. No timing or memory pass/fail thresholds.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time

from baseline import ROOT, SNAPSHOT, materialize, semantics

SUITE = ROOT / 'scripts/availability-suite.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def worker(argv):
    metrics, *args = argv
    from calendar_audit.availability_cli import main
    from calendar_audit import __file__ as origin
    code = main(args)
    status = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines())
    peak, unit = status['VmHWM'].split()
    assert unit == 'kB'
    Path(metrics).write_text(json.dumps({'peak_rss_kib':int(peak),
        'getrusage_maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, 'import_origin':origin}))
    return code


def inputs(case):
    base = datetime(2026,1,1,tzinfo=timezone.utc)
    events = []
    for i in range(case['events']):
        start = base + timedelta(seconds=i*120 if case['kind']=='sparse' else 0)
        end = start + timedelta(seconds=30 if case['kind'] in ('sparse','daily') else 3600)
        extra = '\nRRULE:FREQ=DAILY;COUNT=90' if case['kind']=='daily' else ('\nRRULE:FREQ=MONTHLY' if case['kind']=='unsupported' else '')
        events.append(f'BEGIN:VEVENT\nUID:{i}\nDTSTART:{start:%Y%m%dT%H%M%SZ}\nDTEND:{end:%Y%m%dT%H%M%SZ}{extra}\nEND:VEVENT\n')
    return ('BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Occurrence suite//EN\n'+''.join(events)+'END:VCALENDAR\n').encode()


def stable(run):
    return {k:v for k,v in run.items() if k not in ('elapsed_seconds','peak_rss_kib','getrusage_maxrss_kib','implementation','repetition','position')}


def run_suite(output, repeats, replay=None):
    assert platform.system() == 'Linux'
    suite = json.loads(SUITE.read_text())
    result = dict(schema_version=1, measured_at_utc=datetime.now(timezone.utc).isoformat(),
        method=__doc__, suite=suite, suite_sha256=digest(SUITE), baseline_sha256=digest(SNAPSHOT),
        scripts_sha256={str(p.relative_to(ROOT)):digest(p) for p in (Path(__file__).resolve(),ROOT/'scripts/baseline.py')},
        candidate_sha256={str(p.relative_to(ROOT)):digest(p) for p in sorted((ROOT/'src/calendar_audit').glob('*.py'))},
        python=platform.python_version(), platform=platform.platform(),
        dependencies={n:metadata.version(n) for n in ('icalendar','tzdata','python-dateutil','six')},
        repeats=repeats, limits={}, workloads=[])
    from calendar_audit.core import Limits
    from dataclasses import asdict
    result['limits'] = asdict(Limits())
    if replay:
        for key in ('suite_sha256','baseline_sha256','scripts_sha256','candidate_sha256','dependencies'):
            assert result[key] == replay[key], key
    with tempfile.TemporaryDirectory(prefix='occurrence-benchmark-') as temp:
        base = Path(temp)
        baseline_src = materialize(base/'baseline')
        specpath = base/'working.json'
        specpath.write_text(json.dumps(suite['spec'],sort_keys=True)+'\n')
        for index,case in enumerate(suite['workloads']):
            source = base/(case['name']+'.ics')
            source.write_bytes(inputs(case))
            before = {p.name:digest(p) for p in (source,specpath)}
            record = dict(name=case['name'],input_sha256=before,input_bytes=source.stat().st_size,runs=[])
            for repeat in range(repeats):
                order = ['baseline','candidate'] if repeat%2==0 else ['candidate','baseline']
                for position,implementation in enumerate(order):
                    out = base/f'{index}-{repeat}-{implementation}'
                    metrics = base/'metrics.json'
                    env = {**os.environ,'PYTHONPATH':str(baseline_src if implementation=='baseline' else ROOT/'src'), 'PYTHONNOUSERSITE':'1'}
                    cmd = [sys.executable,str(Path(__file__).resolve()),'--worker',str(metrics),str(source),'--spec',str(specpath),'--output',str(out),*case.get('flags',[])]
                    started = time.perf_counter()
                    process = subprocess.run(cmd,env=env,cwd=base,capture_output=True,timeout=35)
                    elapsed = time.perf_counter()-started
                    measurement = json.loads(metrics.read_text())
                    assert measurement['import_origin'].startswith(env['PYTHONPATH'])
                    run = dict(implementation=implementation,repetition=repeat,position=position,
                        elapsed_seconds=elapsed,peak_rss_kib=measurement['peak_rss_kib'],
                        getrusage_maxrss_kib=measurement['getrusage_maxrss_kib'],exit_code=process.returncode)
                    assert process.returncode in (0,2),process.stderr.decode()
                    if out.exists():
                        report = json.loads((out/'report.json').read_text())
                        assert report['complete'] == (process.returncode == 0)
                        assert report['complete'] or (not report['candidates'] and report['candidate_seconds'] is None)
                        run.update(complete=report['complete'],candidate_seconds=report['candidate_seconds'],candidates=len(report['candidates']),
                            output_sha256={p.name:digest(p) for p in sorted(out.iterdir())},
                            output_bytes={p.name:p.stat().st_size for p in sorted(out.iterdir())},
                            semantic_sha256=hashlib.sha256(json.dumps(semantics(report),sort_keys=True).encode()).hexdigest())
                    else:
                        assert process.returncode == 2 and b'INCOMPLETE' in process.stderr
                        run.update(complete=False,failure=process.stderr.decode().strip())
                    assert before == {p.name:digest(p) for p in (source,specpath)}
                    assert not list(base.glob('.calendar-audit-*'))
                    record['runs'].append(run)
            for implementation in ('baseline','candidate'):
                runs = [r for r in record['runs'] if r['implementation']==implementation]
                assert all(stable(r)==stable(runs[0]) for r in runs)
                if replay:
                    expected = next(r for r in replay['workloads'][index]['runs'] if r['implementation']==implementation)
                    assert stable(runs[0]) == stable(expected),(case['name'],implementation)
            a,b = record['runs'][:2]
            if 'semantic_sha256' in a and 'semantic_sha256' in b:
                assert a['semantic_sha256']==b['semantic_sha256'],case['name']
            # Analytic checks independent of the production union implementation.
            b = next(r for r in record['runs'] if r['implementation']=='candidate')
            if not case.get('flags') and case['kind'] != 'unsupported':
                busy = (case['events']*30 if case['kind']=='sparse' else 90*30 if case['kind']=='daily' else 3600)
                assert b['exit_code']==0 and b['candidate_seconds']==90*86400-busy
            result['workloads'].append(record)
            print(case['name']+': '+', '.join(f"{k} median {statistics.median(r['elapsed_seconds'] for r in record['runs'] if r['implementation']==k):.3f}s" for k in ('baseline','candidate')),flush=True)
    output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')


def main():
    if sys.argv[1:2] == ['--worker']:
        return worker(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--replay',type=Path)
    args = parser.parse_args()
    replay = json.loads(args.replay.read_text()) if args.replay else None
    run_suite(args.output,1 if replay else 6,replay)
    return 0


if __name__=='__main__':
    sys.exit(main())
