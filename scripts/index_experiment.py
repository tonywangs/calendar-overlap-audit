"""Authenticate and load the two fixed implementations used by the experiment."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'tests/baseline/occurrence-pipeline.json'
CANDIDATE = ROOT / 'experiments/indexed_availability.py'
SUITE = ROOT / 'scripts/index-suite.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def materialize(destination, candidate=False):
    sources = json.loads(SNAPSHOT.read_text())
    expected = json.loads((ROOT / 'results/benchmark-occurrences.json').read_text())['candidate_sha256']
    assert {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sources.items()} == expected
    for name, text in sources.items():
        assert name.startswith('src/calendar_audit/') and '..' not in Path(name).parts
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    if candidate:
        (destination / 'src/calendar_audit/availability.py').write_bytes(CANDIDATE.read_bytes())
    return destination / 'src'


def load_availability(destination, candidate=False):
    src = materialize(destination, candidate)
    name = 'calendar_index_candidate' if candidate else 'calendar_index_baseline'
    spec = importlib.util.spec_from_file_location(name, src / 'calendar_audit/__init__.py',
        submodule_search_locations=[str(src / 'calendar_audit')])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return __import__(name + '.availability', fromlist=['availability'])
