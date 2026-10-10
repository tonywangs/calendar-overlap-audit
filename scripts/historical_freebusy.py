"""Authenticate and reconstruct historical benchmark source, never its results."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT/'tests/baseline/freebusy-v1.json'


def authenticate(kind):
    saved = json.loads((ROOT/f'results/benchmark-{kind}.json').read_text())
    frozen = json.loads(SNAPSHOT.read_text())
    for name, expected in saved['implementation_sha256'].items():
        assert hashlib.sha256(frozen[name].encode()).hexdigest() == expected, name
        # Only the new entry point changes packaging. Existing production source
        # must still match its measured implementation, independently of snapshot.
        if name != 'pyproject.toml':
            assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected, name
    if kind == 'schedule':
        # benchmark_schedule's worker imports benchmark_index, which imports this
        # helper. Its historical hash belongs to the index experiment evidence.
        expected = json.loads((ROOT/'results/benchmark-index.json').read_text())['script_sha256']['index_experiment.py']
        name = 'scripts/index_experiment.py'
        assert hashlib.sha256(frozen[name].encode()).hexdigest() == expected
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected
    return saved, frozen


def materialize(kind, target):
    saved, frozen = authenticate(kind)
    names = list(saved['implementation_sha256'])
    if kind == 'schedule':
        names.append('scripts/index_experiment.py')
    for name in names:
        path = target/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(frozen[name])
    return target/'src'
