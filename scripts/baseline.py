"""Materialize the frozen catalog implementation for offline comparisons."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'tests/baseline/availability-v1.json'


def materialize(destination):
    sources = json.loads(SNAPSHOT.read_text())
    # Historical evidence authenticates the snapshot, not the evolved candidate.
    for filename in ('benchmark-v0.2.json', 'benchmark-availability-v1.json'):
        saved = json.loads((ROOT / 'results' / filename).read_text())
        expected = {**saved['implementation_sha256'], **saved.get('scripts_sha256', {})}
        if 'benchmark_script_sha256' in saved:
            expected['scripts/benchmark.py'] = saved['benchmark_script_sha256']
        for name, digest in expected.items():
            assert hashlib.sha256(sources[name].encode()).hexdigest() == digest, name
    for name, source in sources.items():
        assert name.startswith(('src/calendar_audit/', 'scripts/')) and '..' not in Path(name).parts
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    return destination / 'src'


def load_package(destination):
    src = materialize(destination)
    name = 'calendar_audit_baseline'
    spec = importlib.util.spec_from_file_location(name, src / 'calendar_audit/__init__.py',
        submodule_search_locations=[str(src / 'calendar_audit')])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def semantics(report):
    """Everything except the explicitly versioned pair-computation surface."""
    result = json.loads(json.dumps(report))
    result.pop('schema_version')
    result['limits'].pop('pairs', None)
    audit = result['audit']
    audit.pop('schema_version')
    audit.pop('report_type', None)
    audit.pop('overlaps', None)
    audit['limits'].pop('pairs', None)
    audit['counts'].pop('pairs', None)
    return result
