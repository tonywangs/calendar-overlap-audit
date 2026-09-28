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
