#!/usr/bin/env python3
"""One-command offline verification, including all preserved historical gates."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

from freebusy_cases import CREATED, UID, instant, read_export
from freebusy_examples import EXAMPLES
from verify import publication_bounds, run

ROOT = Path(__file__).resolve().parents[1]


def installed():
    with tempfile.TemporaryDirectory(prefix='freebusy-installed-') as temp:
        base = Path(temp)
        wheels = base/'wheels'
        wheels.mkdir()
        run([sys.executable,'-m','pip','wheel','--no-index','--no-deps','--no-build-isolation',
             '--wheel-dir',wheels,ROOT],cwd=base)
        envdir = base/'env'
        venv.EnvBuilder(with_pip=False,system_site_packages=False).create(envdir)
        run([sys.executable,'-m','pip','--python',envdir/'bin/python','install','--no-index','--no-cache-dir',
             '--find-links',ROOT/'.cache/wheels',next(wheels.glob('*.whl'))],cwd=base)
        guard = base/'offline'
        guard.mkdir()
        (guard/'sitecustomize.py').write_text(
            'import os,socket\ndef denied(*a,**k):\n os.write(2,b"Unexpected network access\\n")\n os._exit(97)\n'
            'socket.socket=socket.create_connection=socket.getaddrinfo=denied\n')
        env = {**os.environ,'PYTHONPATH':str(guard),'PYTHONNOUSERSITE':'1'}
        run([envdir/'bin/python','-c','import calendar_audit,sys; assert calendar_audit.__file__.startswith(sys.prefix)'],cwd=base,env=env)
        for example in EXAMPLES:
            source=base/(example['name']+'.ics')
            source.write_bytes((ROOT/example['source']).read_bytes())
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            for repetition in range(2):
                output=base/f"{example['name']}-{repetition}"
                run([envdir/'bin/calendar-freebusy',source,'--start',example['start'],'--end',example['end'],
                     '--timezone',example['timezone'],'--all-day','ignore','--uid',UID,'--created-at',CREATED,
                     '--output',output],cwd=base,env=env)
                raw=(output/'busy.ics').read_bytes()
                read_export(raw,instant(example['lo']),instant(example['hi']),
                            [(instant(a),instant(b)) for a,b in example['periods']])
                assert raw == (ROOT/'examples/freebusy'/f"{example['name']}-busy.ics").read_bytes()
                assert sorted(p.name for p in output.iterdir()) == ['busy.ics']
                assert hashlib.sha256(source.read_bytes()).hexdigest() == before
        print('Installed CLI: four synthetic workflows, repeated byte-identically, sockets denied, input hashes unchanged.',flush=True)


def evidence():
    from benchmark_freebusy import NAMES, implementation_hashes, inputs, stable
    from historical_freebusy import authenticate
    saved, _ = authenticate('freebusy')
    assert saved['repetitions'] == 2 and [w['name'] for w in saved['workloads']] == NAMES
    for workload in saved['workloads']:
        raws,*_=inputs(workload['name'])
        assert workload['input_sha256'] == {f"{workload['name']}-{i}.ics":hashlib.sha256(raw).hexdigest() for i,raw in enumerate(raws)}
        assert len(workload['runs']) == 2
        for result in workload['runs']:
            assert stable(result)==stable(workload['runs'][0])
            assert 0 < result['cli_seconds'] < result['elapsed_seconds'] and result['peak_rss_kib'] > 0
    print('Free/busy evidence: source, dependency protocol and generated input hashes authenticated.',flush=True)


def main():
    evidence()
    run([sys.executable,ROOT/'scripts/verify_schedule.py'],cwd=ROOT)
    installed()
    with tempfile.TemporaryDirectory(prefix='freebusy-replay-') as temp:
        from historical_freebusy import materialize
        historical = Path(temp)/'historical'
        src = materialize('freebusy', historical)
        run([sys.executable,historical/'scripts/benchmark_freebusy.py','--replay',ROOT/'results/benchmark-freebusy.json',
             '--output',Path(temp)/'replay.json'],cwd=ROOT,
            env={**os.environ, 'PYTHONPATH':str(src), 'PYTHONNOUSERSITE':'1'})
    publication_bounds()
    run(['git','diff','--check'],cwd=ROOT)
    print('Free/busy verification passed: seeded oracle, independent parser, CLI failures, installed workflows and measured workload replay.',flush=True)


if __name__=='__main__':
    main()
