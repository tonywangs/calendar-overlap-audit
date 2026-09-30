#!/usr/bin/env python3
"""One-command offline verification after the documented dependency preparation.

The installed-wheel check uses a fresh environment without system site packages,
installs only from a predownloaded wheelhouse, and runs outside the repository.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    print('+', ' '.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True, **kwargs)


def installed_example():
    with tempfile.TemporaryDirectory(prefix='calendar-installed-') as temp:
        base = Path(temp)
        wheels = base / 'wheels'
        wheels.mkdir()
        run([sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-deps', '--no-build-isolation',
             '--wheel-dir', wheels, ROOT], cwd=base)
        envdir = base / 'isolated'
        venv.EnvBuilder(with_pip=False, system_site_packages=False).create(envdir)
        python = envdir / 'bin/python'
        wheel = next(wheels.glob('calendar_overlap_audit-*.whl'))
        run([sys.executable, '-m', 'pip', '--python', python, 'install', '--no-index',
             '--no-cache-dir', '--find-links', ROOT / '.cache/wheels', wheel], cwd=base)
        source = base / 'synthetic.ics'
        source.write_bytes((ROOT / 'tests/fixtures/synthetic.ics').read_bytes())
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        # Guard sockets in the installed CLI process. A network attempt is a hard
        # failure, even if the application catches the resulting exception.
        guard = base / 'offline-guard'
        guard.mkdir()
        (guard / 'sitecustomize.py').write_text(
            'import os, socket\n'
            'def denied(*args, **kwargs):\n'
            '    os.write(2, b"Unexpected network access\\n")\n'
            '    os._exit(97)\n'
            'socket.socket = denied\nsocket.create_connection = denied\nsocket.getaddrinfo = denied\n')
        env = {**os.environ, 'PYTHONPATH': str(guard), 'PYTHONNOUSERSITE': '1'}
        output = base / 'report'
        run([envdir / 'bin/calendar-audit', source, '--start', '2026-03-06', '--end', '2026-03-11',
             '--timezone', 'America/New_York', '--output', output], cwd=base, env=env)
        report = json.loads((output / 'report.json').read_text())
        assert report['complete'] and report['occupied_seconds'] == 23400
        assert len(report['overlaps']) == 3 and len(report['occurrences']) == 11
        assert report['sources'][0]['sha256'] == before == hashlib.sha256(source.read_bytes()).hexdigest()
        override_source = base / 'overrides.ics'
        override_source.write_bytes((ROOT / 'tests/fixtures/overrides.ics').read_bytes())
        override_hash = hashlib.sha256(override_source.read_bytes()).hexdigest()
        override_output = base / 'override-report'
        run([envdir / 'bin/calendar-audit', override_source, '--start', '2026-03-03', '--end', '2026-03-06',
             '--timezone', 'UTC', '--output', override_output], cwd=base, env=env)
        changed = json.loads((override_output / 'report.json').read_text())
        assert changed['complete'] and changed['occupied_seconds'] == 9000
        assert len(changed['overlaps']) == 3 and len(changed['occurrences']) == 3
        assert len(changed['cancellations']) == 1 and changed['schema_version'] == 2
        assert changed['sources'][0]['sha256'] == override_hash == hashlib.sha256(override_source.read_bytes()).hexdigest()
        spec = base / 'working-v1.json'
        spec.write_bytes((ROOT / 'examples/working-v1.json').read_bytes())
        spec_hash = hashlib.sha256(spec.read_bytes()).hexdigest()
        available_output = base / 'availability-report'
        run([envdir / 'bin/calendar-availability', source, '--spec', spec,
             '--output', available_output], cwd=base, env=env)
        available = json.loads((available_output / 'report.json').read_text())
        assert available['complete'] and available['candidate_seconds'] == 50400
        assert len(available['candidates']) == 2
        assert available['spec_source']['sha256'] == spec_hash == hashlib.sha256(spec.read_bytes()).hexdigest()
        assert available['audit']['sources'][0]['sha256'] == before == hashlib.sha256(source.read_bytes()).hexdigest()
        for name in ('report.json', 'report.html'):
            assert (available_output / name).read_bytes() == (ROOT / 'examples/availability-report' / name).read_bytes()
        # Confirm import origin belongs to the isolated environment, not editable src.
        run([python, '-c', 'import calendar_audit,sys; assert calendar_audit.__file__.startswith(sys.prefix)'], cwd=base, env=env)
        print('Isolated installed CLI: offline, expected occupancy/pairs, input hash unchanged.', flush=True)


def publication_bounds():
    excluded = {'.git', '.venv', '.cache', '.pytest_cache', '__pycache__', 'build', 'dist'}
    paths = [p for p in ROOT.rglob('*') if p.is_file() and not any(
        part in excluded or part.endswith('.egg-info') for part in p.relative_to(ROOT).parts)]
    assert len(paths) <= 1000
    assert sum(p.stat().st_size for p in paths) <= 32 * 1024 * 1024
    assert all(p.stat().st_size <= 10 * 1024 * 1024 for p in paths)
    assert all(p.suffix != '.log' or p.relative_to(ROOT).as_posix() == 'results/tests.log' for p in paths)
    print(f'Publication bounds: {len(paths)} files, {sum(p.stat().st_size for p in paths)} bytes.', flush=True)


def evidence_checks():
    from calendar_audit.core import Budget, Limits, analyze
    from calendar_audit.report import html_bytes, json_bytes
    measured = json.loads((ROOT / 'results/benchmark-v0.2.json').read_text())
    for name, expected in measured['implementation_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    assert hashlib.sha256((ROOT / 'scripts/benchmark.py').read_bytes()).hexdigest() == measured['benchmark_script_sha256']
    for workload in measured['workloads']:
        hashes = [r['output_sha256'] for r in workload['runs'] if 'output_sha256' in r]
        assert not hashes or all(h == hashes[0] for h in hashes)
    report = analyze([ROOT / 'tests/fixtures/overrides.ics'], '2026-03-03', '2026-03-06', 'UTC')
    assert json_bytes(report) == (ROOT / 'examples/override-report/report.json').read_bytes()
    assert html_bytes(report, Budget(Limits())) == (ROOT / 'examples/override-report/report.html').read_bytes()
    print('Saved measurements match implementation hashes; override example reproduced byte for byte.', flush=True)
    from calendar_audit.availability import availability, load_spec
    from calendar_audit.availability_report import html_bytes as availability_html
    measured = json.loads((ROOT / 'results/benchmark-availability-v1.json').read_text())
    for name, expected in {**measured['implementation_sha256'], **measured['scripts_sha256']}.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    for workload in measured['workloads']:
        hashes = [r.get('output_sha256') for r in workload['runs']]
        assert all(h == hashes[0] for h in hashes)
    spec, fingerprint = load_spec(ROOT / 'examples/working-v1.json')
    available = availability([ROOT / 'tests/fixtures/synthetic.ics'], spec, spec_source=fingerprint)
    assert json_bytes(available) == (ROOT / 'examples/availability-report/report.json').read_bytes()
    assert availability_html(available, Budget(Limits())) == (ROOT / 'examples/availability-report/report.html').read_bytes()
    print('Availability measurements match implementation hashes; example reproduced byte for byte.', flush=True)


def availability_workloads():
    with tempfile.TemporaryDirectory(prefix='availability-evidence-') as temp:
        output = Path(temp) / 'measurements.json'
        run([sys.executable, ROOT / 'scripts/benchmark_availability.py', '--repeats', '1', '--output', output], cwd=ROOT)
        actual = json.loads(output.read_text())
        saved = json.loads((ROOT / 'results/benchmark-availability-v1.json').read_text())
        assert [w['name'] for w in actual['workloads']] == [w['name'] for w in saved['workloads']]
        for a, b in zip(actual['workloads'], saved['workloads']):
            assert a['input_sha256'] == b['input_sha256']
            for key in ('exit_code', 'output_sha256', 'candidate_seconds', 'candidates', 'failure'):
                assert a['runs'][0].get(key) == b['runs'][0].get(key), (a['name'], key)
    print('Availability workload outputs reproduced; runtime and memory are observations, not thresholds.', flush=True)


def main():
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.cache/ms-playwright'))
    run([sys.executable, '-m', 'pip', 'check'], cwd=ROOT)
    command = [sys.executable, '-m', 'pytest', '-q']
    print('+', ' '.join(command), flush=True)
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, end='', flush=True)
    (ROOT / 'results').mkdir(exist_ok=True)
    (ROOT / 'results/tests.log').write_text(result.stdout)
    result.check_returncode()
    installed_example()
    with tempfile.TemporaryDirectory(prefix='calendar-comparison-') as temp:
        result = Path(temp) / 'comparison.json'
        run([sys.executable, ROOT / 'scripts/compare_recurrence.py', '--output', result], cwd=ROOT)
        assert json.loads(result.read_text()) == json.loads((ROOT / 'results/recurrence-comparison.json').read_text())
    evidence_checks()
    availability_workloads()
    publication_bounds()
    print('Verification passed: unit/oracle/CLI/browser checks and isolated installed CLI.', flush=True)


if __name__ == '__main__':
    main()
