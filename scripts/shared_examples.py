#!/usr/bin/env python3
"""Reproduce the complete synthetic two-participant example into a new directory."""
import argparse
import json
from pathlib import Path
import tempfile

from calendar_audit.core import Budget
from calendar_audit.freebusy import calendar_bytes, occupied
from calendar_audit.shared import discover
from calendar_audit.shared_input import SharedLimits
from calendar_audit.shared_report import html_bytes, json_bytes
from shared_cases import person

UID='5e603c28-3e93-4cf5-9e25-0e0e48aab378'
CREATED='2026-10-10T01:00:00Z'


def event_calendar(start,end):
    return (f'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Synthetic meeting example//EN\r\n'
            f'BEGIN:VEVENT\r\nUID:synthetic-event\r\nDTSTART:{start}\r\nDTEND:{end}\r\n'
            'SUMMARY:Synthetic commitment (excluded from occupancy export)\r\n'
            'END:VEVENT\r\nEND:VCALENDAR\r\n').encode()


def example_inputs():
    calendars={'alex-calendar.ics':event_calendar('20260309T140000Z','20260309T150000Z'),
               'sam-calendar.ics':event_calendar('20260309T153000Z','20260309T160000Z')}
    weekly={'MO':[['09:00','17:00']],'TU':[['09:00','17:00']]}
    spec=dict(version=1,start='2026-03-09T00:00:00Z',end='2026-03-11T00:00:00Z',duration_seconds=1800,
              participants=[person('Alex (synthetic)',['alex-busy.ics'],weekly,'America/New_York'),
                            person('Sam (synthetic)',['sam-busy.ics'],weekly,'Europe/London')])
    raws=dict(calendars)
    # Export in two zones to make Sam's coverage end at 15:00 UTC on March 10.
    # The export zone determines coverage dates, independently of working timezone.
    from calendar_audit.core import Limits
    with tempfile.TemporaryDirectory(prefix='shared-example-') as temp:
        for alias,zone in [('alex','UTC'),('sam','Asia/Tokyo')]:
            path=Path(temp)/f'{alias}.ics';path.write_bytes(calendars[f'{alias}-calendar.ics'])
            occupancy=occupied([path],'2026-03-09','2026-03-11',zone,'ignore')
            raws[f'{alias}-busy.ics']=calendar_bytes(occupancy,Budget(Limits()),uid=UID,created_at=CREATED)
    return spec,raws


EXPECTED=[('2026-03-09T13:00:00Z','2026-03-09T14:00:00Z'),
          ('2026-03-09T15:00:00Z','2026-03-09T15:30:00Z'),
          ('2026-03-09T16:00:00Z','2026-03-09T17:00:00Z'),
          ('2026-03-10T13:00:00Z','2026-03-10T15:00:00Z')]


def check(report):
    assert [(w['start'],w['end']) for w in report['windows']]==EXPECTED
    assert report['window_seconds']==16200 and not report['coverage_complete']
    assert report['participants'][1]['coverage_gaps']==[
        dict(start='2026-03-10T15:00:00Z',end='2026-03-11T00:00:00Z',seconds=32400)]


def generate(directory):
    from shared_cases import write_case
    directory.mkdir()
    spec,raws=example_inputs()
    path=write_case(directory,spec,raws)
    report=discover(path);check(report)
    (directory/'report.json').write_bytes(json_bytes(report,Budget(SharedLimits())))
    (directory/'report.html').write_bytes(html_bytes(report,Budget(SharedLimits())))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    generate(parser.parse_args().output)
