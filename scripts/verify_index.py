#!/usr/bin/env python3
"""Verify frozen evidence and candidate regressions; optionally remeasure all pairs.

Run after dependency setup: .venv/bin/python scripts/verify_index.py
Full experiment: .venv/bin/python scripts/verify_index.py --measure /tmp/index-new.json
Performance observations may change across hosts; fresh timing is never asserted
against historical timing. Exact outputs and frozen protocol hashes are asserted.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from index_experiment import ROOT, CANDIDATE, SUITE, SNAPSHOT, digest, materialize
from benchmark_index import evaluate, inputs, specification, stable


def run(command, **kwargs):
    print('+', ' '.join(map(str,command)),flush=True)
    subprocess.run(list(map(str,command)),check=True,**kwargs)


def evidence():
    frozen = json.loads((ROOT/'experiments/index-freeze.json').read_text())
    for name,expected in frozen['sha256'].items():
        assert digest(ROOT/name) == expected, name
    saved = json.loads((ROOT/'results/benchmark-index.json').read_text())
    assert datetime.fromisoformat(frozen['frozen_at_utc']) < datetime.fromisoformat(saved['measured_at_utc'])
    assert saved['suite_sha256'] == digest(SUITE)
    assert saved['suite'] == json.loads(SUITE.read_text())
    assert saved['baseline_sha256'] == digest(SNAPSHOT)
    assert saved['candidate_sha256'] == digest(CANDIDATE)
    assert saved['script_sha256'] == {name:digest(ROOT/'scripts'/name) for name in
        ('benchmark_index.py','index_experiment.py')}
    assert saved['repeats'] == saved['suite']['repetitions'] == 6
    assert len(saved['workloads']) == len(saved['suite']['workloads'])
    for index,(case,workload) in enumerate(zip(saved['suite']['workloads'],saved['workloads'])):
        assert workload['name'] == case['name']
        seed = saved['suite']['seed']+index
        assert workload['seed'] == seed
        assert workload['spec'] == specification(case)
        assert workload['input_sha256'] == {
            case['name']+'.ics':hashlib.sha256(inputs(case,seed)).hexdigest(),
            'working.json':hashlib.sha256((json.dumps(specification(case),sort_keys=True)+'\n').encode()).hexdigest()}
        assert len(workload['runs']) == 12
        for repetition in range(6):
            pair = workload['runs'][2*repetition:2*repetition+2]
            assert [r['implementation'] for r in pair] == (['baseline','candidate'] if repetition%2==0 else ['candidate','baseline'])
            assert [r['position'] for r in pair] == [0,1]
            assert all(r['repetition'] == repetition for r in pair)
        for r in workload['runs']:
            assert stable(r) == stable(workload['runs'][0])
            assert r['complete'] and r['exit_code'] == 0
            assert 0 < r['availability_seconds'] < r['elapsed_seconds']
            assert 0 < r['analysis_seconds'] < r['elapsed_seconds']
            assert 0 < r['peak_rss_kib']
            assert r['elapsed_seconds'] < saved['suite']['limits']['seconds']
    assert saved['evaluation'] == evaluate(saved)
    decision = json.loads((ROOT/'results/index-decision.json').read_text())
    assert decision['benchmark_sha256'] == digest(ROOT/'results/benchmark-index.json')
    assert decision['adopted'] == saved['evaluation']['performance_and_output_gates_pass']
    expected = CANDIDATE.read_text() if decision['adopted'] else json.loads(SNAPSHOT.read_text())['src/calendar_audit/availability.py']
    assert (ROOT/'src/calendar_audit/availability.py').read_text() == expected
    print('Frozen protocol, paired observations, exact hashes and production decision verified.',flush=True)


def candidate_regressions():
    # Prepend a materialized candidate package to override the editable install.
    # Existing tests cover actual CLI cleanup/signals, browser behavior and limits.
    with tempfile.TemporaryDirectory(prefix='index-regressions-') as temp:
        src = materialize(Path(temp),True)
        env = {**os.environ,'PYTHONPATH':str(src),'PYTHONNOUSERSITE':'1',
               'PLAYWRIGHT_BROWSERS_PATH':str(ROOT/'.cache/ms-playwright')}
        run([sys.executable,'-c','import calendar_audit; from pathlib import Path; '
             'assert Path(calendar_audit.__file__).is_relative_to('+repr(str(src))+')'],cwd=ROOT,env=env)
        run([sys.executable,'-m','pytest','-q','tests','--ignore=tests/test_indexed_availability.py'],cwd=ROOT,env=env)
    print('Frozen candidate passed existing regressions with authenticated import origin.',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measure',type=Path,help='Also collect six new pairs per workload into a new file')
    args = parser.parse_args()
    if args.measure:
        assert not args.measure.exists(), 'Choose a new measurements file; historical evidence is never overwritten'
        assert not args.measure.resolve().is_relative_to(ROOT/'results'), 'Use an output outside historical results'
    evidence()
    run([sys.executable,ROOT/'scripts/verify.py'],cwd=ROOT)
    candidate_regressions()
    with tempfile.TemporaryDirectory(prefix='index-replay-') as temp:
        run([sys.executable,ROOT/'scripts/benchmark_index.py','--replay',ROOT/'results/benchmark-index.json',
             '--output',Path(temp)/'replay.json'],cwd=ROOT)
    if args.measure:
        run([sys.executable,ROOT/'scripts/benchmark_index.py','--output',args.measure],cwd=ROOT)
    print('Index verification passed: protocol, exact seeded/oracle results, both CLI paths, browser and replay.',flush=True)


if __name__ == '__main__':
    main()
