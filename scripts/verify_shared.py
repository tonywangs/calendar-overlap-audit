#!/usr/bin/env python3
"""One-command offline verification of shared discovery and all historical gates."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

from shared_examples import CREATED, UID, check, example_inputs, generate
from verify import ROOT, publication_bounds, run


def installed():
    with tempfile.TemporaryDirectory(prefix='shared-installed-') as temp:
        base=Path(temp);wheels=base/'wheels';wheels.mkdir()
        run([sys.executable,'-m','pip','wheel','--no-index','--no-deps','--no-build-isolation',
             '--wheel-dir',wheels,ROOT],cwd=base)
        envdir=base/'env'
        venv.EnvBuilder(with_pip=False,system_site_packages=False).create(envdir)
        run([sys.executable,'-m','pip','--python',envdir/'bin/python','install','--no-index','--no-cache-dir',
             '--find-links',ROOT/'.cache/wheels',next(wheels.glob('*.whl'))],cwd=base)
        guard=base/'offline';guard.mkdir()
        (guard/'sitecustomize.py').write_text(
            'import os,socket\ndef denied(*a,**k):\n os.write(2,b"Unexpected network access\\n")\n os._exit(97)\n'
            'socket.socket=socket.create_connection=socket.getaddrinfo=denied\n')
        env={**os.environ,'PYTHONPATH':str(guard),'PYTHONNOUSERSITE':'1'}
        run([envdir/'bin/python','-c','import calendar_audit.shared,sys; assert calendar_audit.shared.__file__.startswith(sys.prefix)'],cwd=base,env=env)
        example=ROOT/'examples/shared'
        originals={}
        for name in ('manifest.json','alex-calendar.ics','sam-calendar.ics'):
            raw=(example/name).read_bytes();(base/name).write_bytes(raw)
            originals[name]=hashlib.sha256(raw).hexdigest()
        for alias,zone in [('alex','UTC'),('sam','Asia/Tokyo')]:
            output=base/f'export-{alias}'
            run([envdir/'bin/calendar-freebusy',base/f'{alias}-calendar.ics','--start','2026-03-09','--end','2026-03-11',
                 '--timezone',zone,'--all-day','ignore','--uid',UID,'--created-at',CREATED,'--output',output],cwd=base,env=env)
            raw=(output/'busy.ics').read_bytes()
            assert raw==(example/f'{alias}-busy.ics').read_bytes()
            (base/f'{alias}-busy.ics').write_bytes(raw)
            originals[f'{alias}-busy.ics']=hashlib.sha256(raw).hexdigest()
        for rep in range(2):
            output=base/f'shared-{rep}'
            run([envdir/'bin/calendar-shared','--manifest',base/'manifest.json','--output',output],cwd=base,env=env)
            report=json.loads((output/'report.json').read_text());check(report)
            for name in ('report.json','report.html'):
                assert (output/name).read_bytes()==(example/name).read_bytes()
        assert originals=={n:hashlib.sha256((base/n).read_bytes()).hexdigest() for n in originals}
        print('Installed offline workflow: two synthetic calendars → VFREEBUSY → shared windows; isolated import, two identical runs, unchanged input hashes.',flush=True)


def evidence():
    from benchmark_shared import NAMES, implementation_hashes, inputs, stable
    saved=json.loads((ROOT/'results/benchmark-shared.json').read_text())
    assert saved['implementation_sha256']==implementation_hashes()
    assert saved['repetitions']==2 and [w['name'] for w in saved['workloads']]==NAMES
    from shared_cases import write_case
    with tempfile.TemporaryDirectory(prefix='shared-evidence-') as temp:
        for case in saved['workloads']:
            spec,raws,flags,code=inputs(case['name'])
            base=Path(temp)/case['name'];path=write_case(base,spec,raws)
            assert case['input_sha256']=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [path]+[base/n for n in raws]}
            assert case['flags']==flags and len(case['runs'])==2
            for r in case['runs']:
                assert r['exit_code']==code and stable(r)==stable(case['runs'][0])
                assert 0<r['cli_seconds']<r['elapsed_seconds'] and r['peak_rss_kib']>0
        target=Path(temp)/'example';generate(target)
        for path in target.iterdir():
            assert path.read_bytes()==(ROOT/'examples/shared'/path.name).read_bytes(),path.name
    print('Shared evidence: implementation/input hashes, outcomes and complete synthetic example authenticated.',flush=True)


def main():
    evidence()
    run([sys.executable,ROOT/'scripts/verify_freebusy.py'],cwd=ROOT)
    installed()
    with tempfile.TemporaryDirectory(prefix='shared-replay-') as temp:
        run([sys.executable,ROOT/'scripts/benchmark_shared.py','--replay',ROOT/'results/benchmark-shared.json',
             '--output',Path(temp)/'replay.json'],cwd=ROOT)
    publication_bounds()
    run(['git','diff','--check'],cwd=ROOT)
    print('Shared-window verification passed: coverage oracle, independent decoding, failure cleanup, Chromium, installed workflow and workload replay.',flush=True)


if __name__=='__main__':main()
