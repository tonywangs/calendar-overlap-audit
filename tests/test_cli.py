from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from unittest.mock import patch

import pytest

from calendar_audit.cli import deadline, main, write_bundle
from calendar_audit.core import AuditError, Budget, Limits, analyze
from calendar_audit.report import html_bytes
from conftest import FIXTURES


def args(source, output):
    return [str(source), '--start', '2026-03-06', '--end', '2026-03-11',
            '--timezone', 'America/New_York', '--output', str(output)]


def test_cli_exit_codes_and_bundle(tmp_path):
    out = tmp_path / 'report'
    source = FIXTURES / 'synthetic.ics'
    before = source.read_bytes()
    assert main(args(source, out)) == 0
    assert set(p.name for p in out.iterdir()) == {'report.html', 'report.json'}
    data = json.loads((out / 'report.json').read_text())
    assert data['occupied_seconds'] == 23400
    assert (out.stat().st_mode & 0o777) == 0o700
    assert (out / 'report.json').stat().st_mode & 0o777 == 0o600
    assert main(args(source, out)) == 1
    assert main(args(source, source)) == 1
    assert source.read_bytes() == before
    invalid = tmp_path / 'invalid.ics'
    invalid.write_bytes(b'not a calendar')
    assert main(args(invalid, tmp_path / 'incomplete')) == 2
    data = json.loads((tmp_path / 'incomplete/report.json').read_text())
    assert not data['complete'] and data['sources'][0]['sha256'] == hashlib.sha256(invalid.read_bytes()).hexdigest()
    assert 'INCOMPLETE ANALYSIS' in (tmp_path / 'incomplete/report.html').read_text()
    assert main(args(tmp_path / 'missing.ics', tmp_path / 'failed')) == 1
    assert not (tmp_path / 'failed').exists()


@pytest.mark.parametrize('kind', ['directory', 'file', 'symlink', 'dangling'])
def test_output_collisions_preserve_existing_paths(tmp_path, kind):
    out = tmp_path / 'existing'
    if kind == 'directory':
        out.mkdir()
    elif kind == 'file':
        out.write_text('preserve me')
    else:
        out.symlink_to(tmp_path / ('missing' if kind == 'dangling' else 'target'))
        if kind == 'symlink':
            (tmp_path / 'target').write_text('preserve target')
    assert main(args(FIXTURES / 'synthetic.ics', out)) == 1
    assert os.path.lexists(out)
    if kind == 'file':
        assert out.read_text() == 'preserve me'
    if kind == 'symlink':
        assert (tmp_path / 'target').read_text() == 'preserve target'
    assert not list(tmp_path.glob('.calendar-audit-*'))


@pytest.mark.parametrize('failure', ['disk_full', 'rename_second', 'interrupt', 'terminate', 'collision_race'])
def test_failed_write_and_cancel_cleanup(tmp_path, failure):
    out = tmp_path / 'bundle'
    budget = Budget(Limits())
    content = {'report.html': b'html', 'report.json': b'json'}
    real_replace = os.replace
    calls = 0
    def failing_replace(a, b):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('injected failed write')
        return real_replace(a, b)
    def fail(*_):
        if failure == 'interrupt':
            os.kill(os.getpid(), signal.SIGINT)
        elif failure == 'terminate':
            os.kill(os.getpid(), signal.SIGTERM)
        else:
            raise OSError('injected disk full')
    def collision(*_):
        if not out.exists():
            out.mkdir()
            (out / 'owner').write_text('another writer')
    target, effect = ('calendar_audit.cli.os.replace', failing_replace) if failure == 'rename_second' else (
        'calendar_audit.cli.os.fsync', collision if failure == 'collision_race' else fail)
    with deadline(5), patch(target, side_effect=effect):
        with pytest.raises((OSError, KeyboardInterrupt)):
            write_bundle(out, content, budget)
    if failure == 'collision_race':
        assert (out / 'owner').read_text() == 'another writer'
        assert len(list(out.iterdir())) == 1
    else:
        assert not out.exists()
    assert not list(tmp_path.glob('.calendar-audit-*'))


def test_report_limits_and_deadline_leave_no_output(tmp_path):
    for flag, value in [('--max-report-bytes', '50'), ('--max-seconds', '0.000001'),
                        ('--max-occurrences', '1'), ('--max-seconds', 'nan')]:
        out = tmp_path / 'limited'
        assert main(args(FIXTURES / 'synthetic.ics', out) + [flag, value]) == 1
        assert not out.exists() and not list(tmp_path.glob('.calendar-audit-*'))
    r = analyze([FIXTURES / 'synthetic.ics'], '2026-03-06', '2026-03-11', 'America/New_York')
    with pytest.raises(AuditError, match='report_bytes'):
        html_bytes(r, Budget(replace(Limits(), report_bytes=100)))


def test_posix_deadline_interrupts_blocking_work():
    # Tests the asynchronous guard, not only the cooperative budget checks.
    with pytest.raises(AuditError, match='Execution-time'):
        with deadline(.02):
            signal.pause()


def test_cli_subprocess_and_input_preservation(tmp_path):
    source = tmp_path / 'input.ics'
    source.write_bytes((FIXTURES / 'synthetic.ics').read_bytes())
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    proc = subprocess.run([sys.executable, '-m', 'calendar_audit', *args(source, tmp_path / 'out')], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    assert '23400 occupied seconds' in proc.stdout
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_html_determinism_escaping_and_privacy():
    r = analyze([FIXTURES / 'synthetic.ics'], '2026-03-06', '2026-03-11', 'America/New_York')
    a = html_bytes(r, Budget(Limits()))
    assert a == html_bytes(r, Budget(Limits()))
    assert b'PRIVATE_' not in a and b'<img src=' not in a
    assert b'&lt;img' in a and a.count(b'<script>') == 1


def test_cancellation_during_directory_reservation_cleans_owned_path(tmp_path):
    out = tmp_path / 'report'
    real_mkdir = Path.mkdir
    def interrupt_after_mkdir(path, *a, **kw):
        result = real_mkdir(path, *a, **kw)
        if path == out:
            os.kill(os.getpid(), signal.SIGTERM)
        return result
    with deadline(5), patch.object(Path, 'mkdir', interrupt_after_mkdir):
        with pytest.raises(KeyboardInterrupt):
            write_bundle(out, {'report.json': b'{}'}, Budget(Limits()))
    assert not out.exists() and not list(tmp_path.glob('.calendar-audit-*'))
