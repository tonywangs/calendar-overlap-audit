from pathlib import Path
import pytest


FIXTURES = Path(__file__).parent / 'fixtures'


def calendar(*events):
    return 'BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Synthetic test//EN\n' + ''.join(
        'BEGIN:VEVENT\n' + event.strip() + '\nEND:VEVENT\n' for event in events) + 'END:VCALENDAR\n'


@pytest.fixture
def make_ics(tmp_path):
    def make(*events, name='synthetic.ics'):
        path = tmp_path / name
        path.write_text(calendar(*events))
        return path
    return make


@pytest.fixture(scope='session')
def baseline_availability(tmp_path_factory):
    import sys
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    from baseline import load_package
    load_package(tmp_path_factory.mktemp('baseline'))
    return importlib.import_module('calendar_audit_baseline.availability').availability
