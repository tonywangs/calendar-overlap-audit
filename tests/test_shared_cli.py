"""Fail-closed shared CLI: identity, offline round trip, bounds and rollback."""
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
from unittest.mock import patch

import pytest
from calendar_audit.core import AuditError, Budget
from calendar_audit.freebusy_cli import main as export
from calendar_audit.shared import discover
from calendar_audit.shared_cli import main
from calendar_audit.shared_input import SharedLimits
from calendar_audit.shared_report import html_bytes, json_bytes

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from shared_cases import BASE, ics, manifest, person, write_case


def arguments(directory):
    lo,hi=BASE,BASE+timedelta(hours=1)
    p=[(lo+timedelta(minutes=10),lo+timedelta(minutes=20),'BUSY',False),
       (lo+timedelta(minutes=30),lo+timedelta(minutes=40),'BUSY',True)]
    path=write_case(directory,manifest([person('A',['a.ics','b.ics'])]),{'a.ics':ics(lo,hi,p),'b.ics':ics(lo,hi)})
    return ['--manifest',str(path),'--output',str(directory/'out')]


def clean(directory):
    assert not (directory/'out').exists()
    assert not list(directory.glob('.calendar-audit-*'))


def test_success_repeated_and_no_path_metadata(tmp_path):
    args=arguments(tmp_path)
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}
    assert main(args)==0
    assert main(args[:-1]+[str(tmp_path/'again')])==0
    for name in ('report.json','report.html'):
        raw=(tmp_path/'out'/name).read_bytes()
        assert raw==(tmp_path/'again'/name).read_bytes()
        for marker in (b'synthetic-only',b'Synthetic shared windows',b'a.ics',str(tmp_path).encode()):
            assert marker not in raw
        assert (tmp_path/'out'/name).stat().st_mode & 0o777==0o600
    assert (tmp_path/'out').stat().st_mode & 0o777==0o700
    assert before=={name:hashlib.sha256((tmp_path/name).read_bytes()).hexdigest() for name in before}


def test_export_import_roundtrip(tmp_path):
    source=Path(__file__).resolve().parents[1]/'examples/freebusy/ordinary.ics'
    source_before=source.read_bytes()
    dest=tmp_path/'export'
    assert export([str(source),'--start','2026-03-09','--end','2026-03-10','--timezone','UTC',
                   '--all-day','ignore','--output',str(dest)])==0
    spec=manifest([person('A',['export/busy.ics'])])
    path=write_case(tmp_path,spec,{})
    report=discover(path)
    assert report['coverage_complete']
    assert [(w['start'],w['end']) for w in report['windows']]==[('2026-03-09T09:00:00Z','2026-03-09T10:00:00Z')]
    assert source.read_bytes()==source_before


@pytest.mark.parametrize('kind',['directory','file','symlink','dangling'])
def test_output_collision(tmp_path,kind):
    args=arguments(tmp_path);out=tmp_path/'out'
    if kind=='directory':out.mkdir()
    elif kind=='file':out.write_bytes(b'preserve')
    else:
        target=tmp_path/'target'
        if kind=='symlink':target.write_bytes(b'preserve')
        out.symlink_to(target)
    assert main(args)==1 and os.path.lexists(out)
    if kind in ('file','symlink'):assert out.read_bytes()==b'preserve'
    assert not list(tmp_path.glob('.calendar-audit-*'))


@pytest.mark.parametrize('flag,value',[
    ('input-bytes','1'),('manifest-bytes','1'),('files','1'),('line-bytes','5'),('periods','1'),
    ('operations','1'),('intervals','1'),('windows','1'),('report-bytes','50'),('seconds','0.000001'),
])
def test_resource_limits(tmp_path,flag,value):
    assert main(arguments(tmp_path)+['--max-'+flag,value])==2
    clean(tmp_path)


@pytest.mark.parametrize('which',['json','html'])
def test_report_serializers_enforce_limit(tmp_path,which):
    report=discover(Path(arguments(tmp_path)[1]))
    with pytest.raises(AuditError,match='report_bytes'):
        (json_bytes if which=='json' else html_bytes)(report,Budget(SharedLimits(report_bytes=50)))


@pytest.mark.parametrize('failure',['json','html','disk','rename','post_rename','deadline','sigint','sigterm'])
def test_failure_cleanup_and_private_errors(tmp_path,failure,capsys):
    args=arguments(tmp_path);before=(tmp_path/'a.ics').read_bytes();real_replace=os.replace
    def fail(*args,**kwargs):
        if failure in ('sigint','sigterm'):
            os.kill(os.getpid(),signal.SIGINT if failure=='sigint' else signal.SIGTERM)
        if failure=='deadline':raise AuditError('Execution-time limit exceeded')
        if failure=='post_rename':real_replace(*args,**kwargs)
        raise TypeError('PRIVATE serializer') if failure in ('json','html') else OSError('PRIVATE filesystem')
    target={'json':'calendar_audit.shared_cli.json_bytes','html':'calendar_audit.shared_cli.html_bytes',
            'rename':'calendar_audit.cli.os.replace','post_rename':'calendar_audit.cli.os.replace'}.get(failure,'calendar_audit.cli.os.fsync')
    with patch(target,side_effect=fail):
        assert main(args)==(130 if failure in ('sigint','sigterm') else 2 if failure=='deadline' else 1)
    assert 'PRIVATE' not in capsys.readouterr().err
    assert (tmp_path/'a.ics').read_bytes()==before
    clean(tmp_path)


@pytest.mark.parametrize('stage',['calendar_audit.shared.parse_freebusy','calendar_audit.shared_cli.json_bytes','calendar_audit.cli.os.replace'])
@pytest.mark.parametrize('sig',[signal.SIGINT,signal.SIGTERM])
def test_cancellation_at_stages(tmp_path,stage,sig):
    args=arguments(tmp_path)
    old=(signal.getsignal(signal.SIGALRM),signal.getsignal(signal.SIGTERM))
    def cancel(*args,**kwargs):
        os.kill(os.getpid(),sig)
        raise AssertionError('Signal did not interrupt')
    with patch(stage,side_effect=cancel):assert main(args)==130
    assert old==(signal.getsignal(signal.SIGALRM),signal.getsignal(signal.SIGTERM))
    clean(tmp_path)


def test_actual_timer_interrupts_serialization(tmp_path):
    args=arguments(tmp_path)
    def slow(*args,**kwargs):
        time.sleep(2)
        raise AssertionError('Deadline did not interrupt')
    with patch('calendar_audit.shared_cli.json_bytes',side_effect=slow):
        assert main(args+['--max-seconds','0.1'])==2
    clean(tmp_path)


def test_reservation_race_preserves_other_owner(tmp_path):
    args=arguments(tmp_path);out=tmp_path/'out';real=Path.mkdir
    def race(self,*args,**kwargs):
        if self==out:
            real(out);(out/'other').write_bytes(b'preserve')
        return real(self,*args,**kwargs)
    with patch.object(Path,'mkdir',race):assert main(args)==1
    assert (out/'other').read_bytes()==b'preserve'
    assert not list(tmp_path.glob('.calendar-audit-*'))


@pytest.mark.parametrize('kind',['missing','directory','fifo','bad_utf8','duplicate_json','deep_json','empty_ics','double_calendar'])
def test_bad_sources_and_manifest(tmp_path,kind,capsys):
    args=arguments(tmp_path);path=tmp_path/'a.ics'
    if kind=='missing':path.unlink()
    elif kind=='directory':path.unlink();path.mkdir()
    elif kind=='fifo':path.unlink();os.mkfifo(path)
    elif kind=='bad_utf8':path.write_bytes(b'\xffPRIVATE')
    elif kind=='duplicate_json':(tmp_path/'manifest.json').write_bytes(b'{"version":1,"version":1}')
    elif kind=='deep_json':(tmp_path/'manifest.json').write_bytes(b'['*1100+b']'*1100)
    elif kind=='empty_ics':path.write_bytes(b'')
    elif kind=='double_calendar':path.write_bytes(path.read_bytes()*2)
    assert main(args)==1
    assert 'PRIVATE' not in capsys.readouterr().err
    clean(tmp_path)
