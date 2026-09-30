import hashlib
import json
import os
from pathlib import Path
import signal
from unittest.mock import patch

import pytest

from calendar_audit.availability_cli import main
from conftest import FIXTURES
from test_availability import SPEC


def arguments(tmp_path, source=None):
    spec = tmp_path / 'working.json'
    spec.write_text(json.dumps(SPEC))
    return [str(source or FIXTURES / 'synthetic.ics'), '--spec', str(spec), '--output', str(tmp_path / 'out')]


def test_cli_success_determinism_and_preservation(tmp_path):
    argv = arguments(tmp_path)
    before = {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [argv[0],argv[2]]}
    assert main(argv) == 0
    assert main(argv[:-1] + [str(tmp_path / 'again')]) == 0
    for name in ('report.json','report.html'):
        assert (tmp_path / 'out' / name).read_bytes() == (tmp_path / 'again' / name).read_bytes()
        assert (tmp_path / 'out' / name).stat().st_mode & 0o777 == 0o600
    assert before == {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in before}
    assert main(argv) == 1
    assert main(argv[:-1] + [argv[0]]) == 1
    assert main(argv[:-1] + [argv[2]]) == 1


@pytest.mark.parametrize('kind', ['directory','file','symlink','dangling'])
def test_collisions(tmp_path, kind):
    argv = arguments(tmp_path)
    out = tmp_path / 'out'
    if kind == 'directory':
        out.mkdir()
    elif kind == 'file':
        out.write_text('keep')
    else:
        target = tmp_path / 'target'
        if kind == 'symlink':
            target.write_text('keep target')
        out.symlink_to(target)
    assert main(argv) == 1 and os.path.lexists(out)
    if kind == 'file':
        assert out.read_text() == 'keep'
    if kind == 'symlink':
        assert (tmp_path / 'target').read_text() == 'keep target'
    assert not list(tmp_path.glob('.calendar-audit-*'))


@pytest.mark.parametrize('flag,value', [('--max-occurrences','1'), ('--max-candidates','1'),
    ('--max-events','1'), ('--max-input-bytes','1'), ('--max-report-bytes','50'), ('--max-seconds','0.000001')])
def test_exhaustion_is_incomplete_no_bundle(tmp_path, capsys, flag, value):
    assert main(arguments(tmp_path) + [flag,value]) == 2
    assert 'INCOMPLETE' in capsys.readouterr().err
    assert not (tmp_path / 'out').exists() and not list(tmp_path.glob('.calendar-audit-*'))


def test_date_limits_and_invalid_limit(tmp_path):
    argv = arguments(tmp_path)
    specpath = Path(argv[2])
    specpath.write_text(json.dumps({**SPEC, 'end':'2026-03-08'}))
    assert main(argv + ['--max-days','1']) == 2
    assert main(argv + ['--max-days','91']) == 1
    assert main(argv + ['--max-seconds','nan']) == 1
    assert not (tmp_path / 'out').exists()


def test_unsupported_input_diagnostic_bundle(tmp_path, make_ics):
    p = make_ics('UID:bad\nDTSTART:20260306T090000Z\nRRULE:FREQ=MONTHLY')
    assert main(arguments(tmp_path,p)) == 2
    result = json.loads((tmp_path / 'out/report.json').read_text())
    assert not result['complete'] and result['candidates'] == [] and result['candidate_seconds'] is None


@pytest.mark.parametrize('failure', ['json','html','disk','rename','sigint','sigterm'])
def test_failure_and_cancellation_cleanup(tmp_path, failure):
    argv = arguments(tmp_path)
    real_replace = os.replace
    calls = 0
    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if failure in ('sigint','sigterm'):
            os.kill(os.getpid(), signal.SIGINT if failure == 'sigint' else signal.SIGTERM)
        if failure == 'rename' and calls == 1:
            return real_replace(*args, **kwargs)
        raise TypeError('injected serializer failure') if failure in ('json','html') else OSError('injected disk failure')
    target = {'json':'calendar_audit.availability_cli.json_bytes', 'html':'calendar_audit.availability_cli.html_bytes',
              'rename':'calendar_audit.cli.os.replace'}.get(failure,'calendar_audit.cli.os.fsync')
    with patch(target, side_effect=fail):
        assert main(argv) == (130 if failure in ('sigint','sigterm') else 1)
    assert not (tmp_path / 'out').exists() and not list(tmp_path.glob('.calendar-audit-*'))


def test_invalid_spec_boundary_and_missing_source(tmp_path, capsys):
    argv = arguments(tmp_path)
    Path(argv[2]).write_text(json.dumps({**SPEC, 'start':'2026-03-08', 'end':'2026-03-09',
        'timezone':'America/New_York','work_start':'02:30'}))
    assert main(argv) == 1
    assert 'Nonexistent boundary' in capsys.readouterr().err
    argv = arguments(tmp_path, tmp_path / 'missing.ics')
    assert main(argv) == 1
    assert not (tmp_path / 'out').exists()
