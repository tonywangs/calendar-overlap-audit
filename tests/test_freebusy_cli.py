"""Fail-closed CLI, bounded execution, privacy and output ownership checks."""
import hashlib
import os
from pathlib import Path
import signal
import time
from unittest.mock import patch

import pytest
from calendar_audit.core import AuditError, Budget
from calendar_audit.freebusy_cli import main
from conftest import FIXTURES

UID = '5e603c28-3e93-4cf5-9e25-0e0e48aab378'
CREATED = '2026-10-06T01:00:00Z'


def arguments(directory, source=None):
    return [str(source or FIXTURES/'synthetic.ics'), '--start', '2026-03-06', '--end', '2026-03-11',
            '--timezone', 'America/New_York', '--all-day', 'ignore', '--uid', UID,
            '--created-at', CREATED, '--output', str(directory/'out')]


def clean(directory):
    assert not (directory/'out').exists()
    assert not list(directory.glob('.calendar-audit-*'))


def test_success(tmp_path):
    argv = arguments(tmp_path)
    source = Path(argv[0])
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    assert main(argv) == 0
    assert main(argv[:-1] + [str(tmp_path/'again')]) == 0
    out = tmp_path/'out'
    assert sorted(p.name for p in out.iterdir()) == ['busy.ics']
    assert (out/'busy.ics').read_bytes() == (tmp_path/'again/busy.ics').read_bytes()
    assert out.stat().st_mode & 0o777 == 0o700
    assert (out/'busy.ics').stat().st_mode & 0o777 == 0o600
    assert main(argv[:-1] + [str(source)]) == 1
    assert before == hashlib.sha256(source.read_bytes()).hexdigest()


@pytest.mark.parametrize('kind', ['directory', 'file', 'symlink', 'dangling'])
def test_collision(tmp_path, kind):
    out = tmp_path/'out'
    if kind == 'directory':
        out.mkdir()
    elif kind == 'file':
        out.write_bytes(b'preserve')
    else:
        target = tmp_path/'target'
        if kind == 'symlink':
            target.write_bytes(b'preserve')
        out.symlink_to(target)
    assert main(arguments(tmp_path)) == 1 and os.path.lexists(out)
    if kind in ('file', 'symlink'):
        assert out.read_bytes() == b'preserve'
    assert not list(tmp_path.glob('.calendar-audit-*'))


@pytest.mark.parametrize('flag,value', [('--max-occurrences','1'), ('--max-candidates','1'),
    ('--max-events','1'), ('--max-input-bytes','1'), ('--max-line-bytes','5'),
    ('--max-report-bytes','50'), ('--max-seconds','0.000001'), ('--max-intervals','1')])
def test_limits(tmp_path, capsys, flag, value):
    assert main(arguments(tmp_path)+[flag,value]) == 2
    assert 'INCOMPLETE' in capsys.readouterr().err
    clean(tmp_path)


def test_file_and_resolution_limit(tmp_path):
    argv = arguments(tmp_path)
    assert main([argv[0]] + argv + ['--max-files','1']) == 2
    source = FIXTURES/'overrides.ics'
    assert main(arguments(tmp_path, source)+['--max-resolutions','1']) == 2
    clean(tmp_path)


@pytest.mark.parametrize('flag,value', [('--max-seconds','nan'), ('--max-seconds','inf'),
    ('--max-seconds','0'), ('--max-intervals','0'), ('--max-intervals','20001'),
    ('--max-occurrences','20001'), ('--end','2026-03-06'), ('--end','2027-03-11'),
    ('--start','2026-02-30'), ('--timezone','unknown'), ('--uid','PRIVATE'),
    ('--created-at','PRIVATE')])
def test_invalid_arguments(tmp_path, capsys, flag, value):
    assert main(arguments(tmp_path)+[flag,value]) == 1
    assert 'PRIVATE' not in capsys.readouterr().err
    clean(tmp_path)


@pytest.mark.parametrize('raw', [b'garbage', b'\xff', b'BEGIN:VCALENDAR\nVERSION:2.0\n',
    b'BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTODO\nEND:VTODO\nEND:VCALENDAR\n'])
def test_malformed(tmp_path, raw):
    source = tmp_path/'input.ics'
    source.write_bytes(raw)
    assert main(arguments(tmp_path,source)) == 2
    assert source.read_bytes() == raw
    clean(tmp_path)


@pytest.mark.parametrize('fields', [
    'UID:PRIVATE\nDTSTART:20260306T090000Z\nRRULE:FREQ=MONTHLY',
    'UID:PRIVATE\nDTSTART:20260306T090000Z\nDTEND:20260306T080000Z',
    'UID:PRIVATE\nDTSTART;VALUE=DATE:20200101\nRRULE:FREQ=YEARLY',
    'UID:PRIVATE\nRECURRENCE-ID:20260306T090000Z\nSTATUS:CANCELLED',
    'UID:PRIVATE\nDTSTART;TZID=PRIVATE:20260306T090000',
])
def test_incomplete_withholds_even_ignored_and_outside(tmp_path, make_ics, fields, capsys):
    source = make_ics(fields)
    before = source.read_bytes()
    assert main(arguments(tmp_path,source)) == 2
    assert 'PRIVATE' not in capsys.readouterr().err
    assert source.read_bytes() == before
    clean(tmp_path)


def test_conflicting_snapshots(tmp_path, make_ics):
    a = make_ics('UID:shared\nDTSTART:20260306T090000Z\nDTEND:20260306T100000Z', name='a.ics')
    b = make_ics('UID:shared\nDTSTART:20260306T090000Z\nDTEND:20260306T110000Z', name='b.ics')
    assert main([str(b)] + arguments(tmp_path,a)) == 2
    clean(tmp_path)


def test_missing_and_directory_input(tmp_path):
    assert main(arguments(tmp_path,tmp_path/'missing')) == 1
    assert main(arguments(tmp_path,tmp_path)) == 1
    clean(tmp_path)


@pytest.mark.parametrize('failure', ['serialize', 'disk', 'rename', 'post_rename', 'sigint', 'sigterm', 'deadline'])
def test_failure_cleanup(tmp_path, failure):
    source = FIXTURES/'synthetic.ics'
    before = source.read_bytes()
    real_replace = os.replace
    def fail(*args, **kwargs):
        if failure in ('sigint', 'sigterm'):
            os.kill(os.getpid(), signal.SIGINT if failure == 'sigint' else signal.SIGTERM)
        if failure == 'deadline':
            raise AuditError('Execution-time limit exceeded')
        if failure == 'post_rename':
            real_replace(*args, **kwargs)
        raise TypeError('PRIVATE serializer data') if failure == 'serialize' else OSError('PRIVATE disk data')
    target = {'serialize':'calendar_audit.freebusy_cli.calendar_bytes',
              'rename':'calendar_audit.cli.os.replace',
              'post_rename':'calendar_audit.cli.os.replace'}.get(failure,'calendar_audit.cli.os.fsync')
    with patch(target, side_effect=fail):
        assert main(arguments(tmp_path)) == (130 if failure in ('sigint','sigterm') else 2 if failure == 'deadline' else 1)
    assert source.read_bytes() == before
    clean(tmp_path)


@pytest.mark.parametrize('stage', ['calendar_audit.freebusy.analyze_occurrences',
                                  'calendar_audit.freebusy_cli.calendar_bytes', 'calendar_audit.cli.os.replace'])
@pytest.mark.parametrize('signum', [signal.SIGINT, signal.SIGTERM])
def test_signals(tmp_path, stage, signum):
    def cancel(*args, **kwargs):
        os.kill(os.getpid(), signum)
        raise AssertionError('signal not handled')
    old_alarm, old_term = signal.getsignal(signal.SIGALRM), signal.getsignal(signal.SIGTERM)
    with patch(stage, side_effect=cancel):
        assert main(arguments(tmp_path)) == 130
    assert signal.getsignal(signal.SIGALRM) == old_alarm
    assert signal.getsignal(signal.SIGTERM) == old_term
    clean(tmp_path)


def test_actual_deadline_interrupts_blocking_serialization(tmp_path):
    def wait(*args, **kwargs):
        time.sleep(2)
        raise AssertionError('deadline did not interrupt')
    with patch('calendar_audit.freebusy_cli.calendar_bytes', side_effect=wait):
        assert main(arguments(tmp_path)+['--max-seconds','0.15']) == 2
    clean(tmp_path)


def test_output_reservation_race(tmp_path):
    real_mkdir = Path.mkdir
    out = tmp_path/'out'
    def race(self, *args, **kwargs):
        if self == out:
            real_mkdir(out)
            (out/'other-owner').write_bytes(b'preserve')
        return real_mkdir(self, *args, **kwargs)
    with patch.object(Path, 'mkdir', race):
        assert main(arguments(tmp_path)) == 1
    assert (out/'other-owner').read_bytes() == b'preserve'
    assert not list(tmp_path.glob('.calendar-audit-*'))
