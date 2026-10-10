#!/usr/bin/env python3
"""Fresh offline Linux process measurements; two repeats, exact output replay."""
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

from shared_cases import BASE, ics, manifest, person, write_case

ROOT=Path(__file__).resolve().parents[1]
NAMES=['empty_16_people_32_files_90_days','sparse_2000_four_people','dense_20000_sixteen_people',
       'spring_overnight','fall_overnight','disjoint_coverage','period_limit','window_limit',
       'report_limit','operations_limit','runtime_limit']
DAYS=['MO','TU','WE','TH','FR','SA','SU']
ALL={d:[['00:00','24:00']] for d in DAYS}


def digest(raw):return hashlib.sha256(raw).hexdigest()


def inputs(name):
    lo,hi=BASE,BASE+timedelta(days=7)
    flags,expected=[],0
    people,raws=[],{}
    if name=='empty_16_people_32_files_90_days':
        hi=lo+timedelta(days=90)
        mid=lo+timedelta(days=45)
        for p in range(16):
            names=[f'p{p}a.ics',f'p{p}b.ics']
            people.append(person(f'Participant {p}',names,ALL))
            raws[names[0]]=ics(lo,mid);raws[names[1]]=ics(mid,hi)
    elif name in ('spring_overnight','fall_overnight'):
        lo=datetime(2026,3,8,tzinfo=timezone.utc) if name=='spring_overnight' else datetime(2026,11,1,tzinfo=timezone.utc)
        hi=lo+timedelta(days=1)
        people=[person('Night shift',['p.ics'],{'SA':[['23:00','03:00']]},'America/New_York')]
        raws={'p.ics':ics(lo,hi)}
    elif name=='disjoint_coverage':
        mid=lo+timedelta(days=3)
        people=[person('A',['a.ics'],ALL),person('B',['b.ics'],ALL)]
        raws={'a.ics':ics(lo,mid),'b.ics':ics(mid,hi)}
    elif name in ('dense_20000_sixteen_people','period_limit','window_limit'):
        count=20001 if name=='period_limit' else 20000
        people_count=16 if name=='dense_20000_sixteen_people' else 1
        hi=lo+timedelta(days=90)
        for p in range(people_count):
            namefile=f'p{p}.ics';people.append(person(f'P{p}',[namefile],ALL))
            periods=[]
            for i in range(count//people_count):
                a=lo+timedelta(seconds=2*i+1 if name=='window_limit' else 60)
                periods.append((a,a+timedelta(seconds=1),'BUSY',bool(i%2)))
            raws[namefile]=ics(lo,hi,periods)
        if name in ('period_limit','window_limit'):expected=2
    else:
        for p in range(4):
            filename=f'p{p}.ics';people.append(person(f'P{p}',[filename],ALL))
            periods=[]
            for i in range(500):
                a=lo+timedelta(seconds=i*300+30*p)
                periods.append((a,a+timedelta(seconds=15),'BUSY',bool(i%2)))
            raws[filename]=ics(lo,hi,periods)
        if name in ('report_limit','operations_limit','runtime_limit'):
            flags={'report_limit':['--max-report-bytes','1000'],
                   'operations_limit':['--max-operations','100'],
                   'runtime_limit':['--max-seconds','0.000001']}[name]
            expected=2
    return manifest(people,lo,hi,minimum=1),raws,flags,expected


def implementation_hashes():
    names=['pyproject.toml','scripts/benchmark_shared.py','scripts/shared_cases.py']
    names += [p.relative_to(ROOT).as_posix() for p in (ROOT/'src/calendar_audit').glob('*.py')]
    return {name:digest((ROOT/name).read_bytes()) for name in sorted(names)}


def worker(argv):
    import socket
    def denied(*a,**k):os._exit(97)
    socket.socket=socket.create_connection=socket.getaddrinfo=denied
    from calendar_audit.shared_cli import main
    started=time.monotonic();code=main(argv[1:]);elapsed=time.monotonic()-started
    rss=next(int(line.split()[1]) for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmHWM:'))
    Path(argv[0]).write_text(json.dumps(dict(exit_code=code,cli_seconds=elapsed,peak_rss_kib=rss)))


def stable(run):
    return {k:v for k,v in run.items() if k not in ('elapsed_seconds','cli_seconds','peak_rss_kib')}


def expected_windows(name):
    if name=='empty_16_people_32_files_90_days':return 1,90*86400
    if name=='spring_overnight':return 1,3*3600
    if name=='fall_overnight':return 1,5*3600
    if name=='disjoint_coverage':return 0,0
    if name=='dense_20000_sixteen_people':return 2,90*86400-1
    # Four disjoint 15-second blocks per 300-second group over a seven-day horizon.
    if name=='sparse_2000_four_people':return 2000,7*86400-2000*15
    return None


def measure():
    from calendar_audit.shared_input import SharedLimits
    result=dict(schema_version=1,measured_at_utc=datetime.now(timezone.utc).isoformat(),
                method='Two fresh socket-blocked processes per synthetic case. Linux VmHWM is per-process peak RSS. Parent elapsed includes startup. No speedup claim; failures are retained.',
                python=platform.python_version(),platform=platform.platform(),
                dependencies={n:version(n) for n in ('icalendar','tzdata','python-dateutil','six','pytest','playwright')},
                limits=asdict(SharedLimits()),implementation_sha256=implementation_hashes(),repetitions=2,workloads=[])
    with tempfile.TemporaryDirectory(prefix='shared-measure-') as temp:
        base=Path(temp)
        for name in NAMES:
            spec,raws,flags,expected=inputs(name)
            folder=base/name;path=write_case(folder,spec,raws)
            paths=[path]+[folder/n for n in raws]
            hashes={p.name:digest(p.read_bytes()) for p in paths}
            case=dict(name=name,input_sha256=hashes,input_bytes=sum(p.stat().st_size for p in paths),flags=flags,runs=[])
            for rep in range(2):
                output=folder/f'out{rep}';metrics=folder/f'metrics{rep}.json'
                command=[sys.executable,str(Path(__file__).resolve()),'--worker',str(metrics),'--manifest',str(path),'--output',str(output),*flags]
                started=time.monotonic()
                proc=subprocess.run(command,capture_output=True,timeout=40,
                                    env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'PYTHONNOUSERSITE':'1'})
                elapsed=time.monotonic()-started
                assert proc.returncode==0,proc.stderr.decode()
                run=json.loads(metrics.read_text());run['elapsed_seconds']=elapsed
                assert run['exit_code']==expected,proc.stderr.decode()
                run.update(output_bytes={},output_sha256={},windows=None,window_seconds=None,coverage_complete=None)
                if expected==0:
                    report=json.loads((output/'report.json').read_text())
                    run.update(windows=len(report['windows']),window_seconds=report['window_seconds'],coverage_complete=report['coverage_complete'])
                    assert (run['windows'],run['window_seconds'])==expected_windows(name)
                    run['output_bytes']={p.name:p.stat().st_size for p in output.iterdir()}
                    run['output_sha256']={p.name:digest(p.read_bytes()) for p in output.iterdir()}
                else:
                    assert not output.exists()
                    assert 'limit exceeded' in proc.stderr.decode()
                assert not list(folder.glob('.calendar-audit-*'))
                assert hashes=={p.name:digest(p.read_bytes()) for p in paths}
                assert 0<run['cli_seconds']<elapsed and run['peak_rss_kib']>0
                case['runs'].append(run)
            assert stable(case['runs'][0])==stable(case['runs'][1])
            result['workloads'].append(case)
            r=case['runs'][0]
            print(f"{name}: exit {r['exit_code']}; {r['elapsed_seconds']:.3f}s; {r['peak_rss_kib']} KiB; {sum(r['output_bytes'].values())} artifact bytes",flush=True)
    return result


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--worker':worker(sys.argv[2:]);return
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--replay',type=Path)
    args=p.parse_args();assert not args.output.exists(),'Choose a new evidence path'
    actual=measure()
    if args.replay:
        saved=json.loads(args.replay.read_text())
        for key in ('schema_version','python','dependencies','limits','implementation_sha256','repetitions'):
            assert actual[key]==saved[key],key
        assert len(actual['workloads'])==len(saved['workloads'])
        for a,b in zip(actual['workloads'],saved['workloads']):
            assert {k:v for k,v in a.items() if k!='runs'}=={k:v for k,v in b.items() if k!='runs'}
            assert all(stable(r)==stable(b['runs'][0]) for r in a['runs']+b['runs'])
    args.output.write_text(json.dumps(actual,indent=2,sort_keys=True)+'\n')


if __name__=='__main__':main()
