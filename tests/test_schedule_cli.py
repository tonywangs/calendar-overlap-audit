"""Exercise the established CLI failure contract with public v2 schedules."""
import json
from pathlib import Path

import pytest

from calendar_audit.availability_cli import main
from conftest import FIXTURES
from test_schedule import SPEC2
import test_availability_cli as legacy
# Reuse the actual failure injections, collisions, signals and assertions with
# v2 input, rather than maintaining a weaker parallel set of CLI tests.
from test_availability_cli import (
    test_cli_success_determinism_and_preservation,
    test_collisions,
    test_exhaustion_is_incomplete_no_bundle,
    test_unsupported_input_diagnostic_bundle,
    test_failure_and_cancellation_cleanup,
    test_cancellation_during_occurrence_analysis,
)


@pytest.fixture(autouse=True)
def v2_arguments(monkeypatch, tmp_path):
    originals = {}
    def arguments(directory, source=None):
        spec = directory/'working.json'
        spec.write_text(json.dumps(SPEC2))
        source = source or FIXTURES/'synthetic.ics'
        for path in (source, spec):
            originals[path] = path.read_bytes()
        return [str(source), '--spec', str(spec), '--output', str(directory/'out')]
    monkeypatch.setattr(legacy, 'arguments', arguments)
    yield
    assert all(path.read_bytes() == raw for path, raw in originals.items())


@pytest.mark.parametrize('change,code,message', [
    ({'exceptions': [{'date': '2026-03-07', 'windows': []}]*2}, 1, 'Duplicate exception date'),
    ({'weekly': {'FR': [['09:00', '10:00']]*17}}, 2, 'limit exceeded'),
    ({'exceptions': [{'date': '2026-03-07', 'windows': []}]*91}, 2, 'limit exceeded'),
    ({'weekly': {'FR': [['23:00', '01:00']]}}, 1, 'overnight'),
])
def test_schedule_validation_failure(tmp_path, change, code, message, capsys):
    path = tmp_path/'schedule.json'
    path.write_text(json.dumps(dict(SPEC2, **change)))
    before = path.read_bytes()
    assert main([str(FIXTURES/'synthetic.ics'), '--spec', str(path), '--output', str(tmp_path/'out')]) == code
    assert message in capsys.readouterr().err
    assert path.read_bytes() == before
    assert not (tmp_path/'out').exists() and not list(tmp_path.glob('.calendar-audit-*'))


def test_schedule_explanation_deadline_cleanup(tmp_path, monkeypatch):
    from calendar_audit.core import AuditError
    def exhausted(*args):
        raise AuditError('Execution-time limit exceeded')
    monkeypatch.setattr('calendar_audit.schedule.explain_days', exhausted)
    assert main(legacy.arguments(tmp_path)) == 2
    assert not (tmp_path/'out').exists() and not list(tmp_path.glob('.calendar-audit-*'))
