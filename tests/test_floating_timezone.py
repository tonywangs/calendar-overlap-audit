"""Regression for the nonstandard timezone metadata in real Pentabarf exports."""
import json
import pytest
from calendar_audit.core import analyze, analyze_occurrences
from calendar_audit.cli import main


def test_explicit_source_zone_preserves_absolute_events_and_daily_split(make_ics):
    source = make_ics('UID:f\nDTSTART:20250201T003000\nDTEND:20250201T013000',
                      'UID:z\nDTSTART:20250131T233000Z\nDTEND:20250201T003000Z',
                      'UID:t\nDTSTART;TZID=Europe/Brussels:20250201T003000\nDTEND;TZID=Europe/Brussels:20250201T013000')
    report = analyze([source], '2025-01-31', '2025-02-02', 'UTC', floating_timezone='Europe/Brussels')
    assert report['complete']
    assert {o['start'] for o in report['occurrences']} == {'2025-01-31T23:30:00Z'}
    assert report['occupied_seconds'] == 3600
    assert [d['occupied_seconds'] for d in report['daily']] == [1800, 1800]
    assert len(report['overlaps']) == 3


@pytest.mark.parametrize('hint', ['calendar', 'event', 'both'])
def test_nonstandard_hints_require_assertion(make_ics, hint):
    source = make_ics('UID:f\nDTSTART:20250201T150000\nDTEND:20250201T153000' +
                      ('\nTZID:Europe-Brussels' if hint in ('event', 'both') else ''))
    if hint in ('calendar', 'both'):
        source.write_text(source.read_text().replace('VERSION:2.0', 'VERSION:2.0\nX-WR-TIMEZONE:Europe/Brussels'))
    for analyze_fn in (analyze, analyze_occurrences):
        provisional = analyze_fn([source], '2025-02-01', '2025-02-02', 'America/New_York')
        assert not provisional['complete']
        assert 'Nonstandard timezone hint' in provisional['issues'][0]['message']
    report = analyze([source], '2025-02-01', '2025-02-02', 'America/New_York', floating_timezone='Europe/Brussels')
    assert report['complete']
    assert report['occurrences'][0]['local_start'] == '2025-02-01T09:00:00-05:00'


def test_cli_records_assertion_and_rejects_invalid_zone(make_ics, tmp_path):
    source = make_ics('UID:f\nDTSTART:20250201T150000\nDTEND:20250201T153000')
    args = [str(source), '--start', '2025-02-01', '--end', '2025-02-02', '--timezone', 'UTC']
    assert main(args + ['--floating-timezone', '../invalid', '--output', str(tmp_path / 'bad')]) == 1
    assert not (tmp_path / 'bad').exists()
    out = tmp_path / 'good'
    assert main(args + ['--floating-timezone', 'Europe/Brussels', '--output', str(out)]) == 0
    assert json.loads((out / 'report.json').read_text())['floating_timezone'] == 'Europe/Brussels'
    assert 'Operator-selected timezone' in (out / 'report.html').read_text()


def test_floating_recurrence_exclusions_and_overrides(make_ics):
    source = make_ics('UID:r\nDTSTART:20250201T003000\nDTEND:20250201T013000\nRRULE:FREQ=DAILY;COUNT=3\nEXDATE:20250202T003000',
                      'UID:r\nRECURRENCE-ID:20250203T003000\nDTSTART:20250203T013000\nDTEND:20250203T023000')
    report = analyze([source], '2025-01-31', '2025-02-04', 'UTC', floating_timezone='Europe/Brussels')
    assert report['complete']
    assert [o['start'] for o in report['occurrences']] == ['2025-01-31T23:30:00Z', '2025-02-03T00:30:00Z']


def test_all_day_remains_display_civil_date(make_ics):
    source = make_ics('UID:day\nDTSTART;VALUE=DATE:20250201\nDTEND;VALUE=DATE:20250202')
    report = analyze([source], '2025-02-01', '2025-02-02', 'America/New_York', floating_timezone='Europe/Brussels')
    assert report['complete'] and report['occupied_seconds'] == 0
    assert report['events'][0]['timezone'] == 'America/New_York'
    assert report['occurrences'][0]['start'] == '2025-02-01'
    assert report['daily'][0]['all_day_occurrences'] == 1
