#!/usr/bin/env python3
"""One-command offline schedule verification, including preserved historical gates."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def evidence():
    from benchmark_schedule import CASES, SEED, inputs, stable
    path = ROOT/'results/benchmark-schedule.json'
    saved = json.loads(path.read_text())
    assert saved['seed'] == SEED and saved['repetitions'] == 2
    assert [w['name'] for w in saved['workloads']] == CASES
    for name, expected in saved['implementation_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected, name
    for case in saved['workloads']:
        raw, spec = inputs(case['name'])
        assert case['input_sha256'] == {'synthetic.ics': hashlib.sha256(raw).hexdigest(),
                                        'working.json': hashlib.sha256(spec).hexdigest()}
        assert case['spec'] == json.loads(spec)
        assert len(case['runs']) == 2
        for run in case['runs']:
            assert stable(run) == stable(case['runs'][0])
            assert run['elapsed_seconds'] > 0 and run['peak_rss_kib'] > 0
            assert 0 < run['availability_seconds'] < run['elapsed_seconds']
            assert 0 < run['analysis_seconds'] < run['elapsed_seconds']
            assert run['complete'] == (case['name'] != 'incomplete')
            assert run['exit_code'] == (0 if run['complete'] else 2)
            assert max(run['output_bytes'].values()) <= saved['limits']['report_bytes']
    print('Schedule measurements: implementation, seeded inputs, limits and deterministic outputs authenticated.', flush=True)


def main():
    evidence()
    subprocess.run([sys.executable, str(ROOT/'scripts/verify_index.py')], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix='schedule-replay-') as temp:
        from historical_freebusy import materialize
        historical = Path(temp)/'historical'
        src = materialize('schedule', historical)
        subprocess.run([sys.executable, str(historical/'scripts/benchmark_schedule.py'), '--replay',
                        str(ROOT/'results/benchmark-schedule.json'), '--output', str(Path(temp)/'replay.json')],
                       cwd=ROOT, check=True, env={**os.environ, 'PYTHONPATH':str(src), 'PYTHONNOUSERSITE':'1'})
    subprocess.run(['git', 'diff', '--check'], cwd=ROOT, check=True)
    print('Schedule verification passed: production, frozen v1, oracle, browser, installed CLIs and workload replay.', flush=True)


if __name__ == '__main__':
    main()
