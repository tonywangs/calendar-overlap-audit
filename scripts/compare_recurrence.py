#!/usr/bin/env python3
"""Pinned independent recurrence comparison on small synthetic inputs, offline."""
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import tempfile

from icalendar import Calendar
import recurring_ical_events
from calendar_audit.core import analyze


def calendar(*components):
    return ('BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Synthetic comparison//EN\n' + ''.join(
        'BEGIN:VEVENT\n'+c+'\nEND:VEVENT\n' for c in components) + 'END:VCALENDAR\n').encode()


def fixtures():
    for freq in ['DAILY', 'WEEKLY']:
        # Original identities before and after the query, effective starts inside.
        for day in [1,8,15]:
            master = f'UID:s\nDTSTART:20260301T100000Z\nDTEND:20260301T110000Z\nRRULE:FREQ={freq};COUNT=20'
            change = (f'UID:s\nRECURRENCE-ID:202603{day:02d}T100000Z\n'
                      'DTSTART:20260305T090000Z\nDTEND:20260305T103000Z')
            cancel = 'UID:s\nRECURRENCE-ID:20260322T100000Z\nDTSTART:20260322T100000Z\nSTATUS:CANCELLED'
            # Cancellation membership requires day 22 for weekly, day 2 for daily.
            if freq == 'DAILY':
                cancel = cancel.replace('20260322','20260302')
            yield f'{freq.lower()}-move-{day}', calendar(master,change,cancel), 'agreement'
    yield 'all-day', calendar(
        'UID:s\nDTSTART;VALUE=DATE:20260301\nDTEND;VALUE=DATE:20260303\nRRULE:FREQ=DAILY;COUNT=10\nEXDATE;VALUE=DATE:20260302',
        'UID:s\nRECURRENCE-ID;VALUE=DATE:20260308\nDTSTART;VALUE=DATE:20260305\nDTEND;VALUE=DATE:20260308'), 'agreement'
    yield 'inherited-duration', calendar(
        'UID:s\nDTSTART:20260301T100000Z\nDTEND:20260301T110000Z\nRRULE:FREQ=DAILY;COUNT=8',
        'UID:s\nRECURRENCE-ID:20260305T100000Z\nDTSTART:20260305T120000Z'), 'policy_difference'
    yield 'spring-generated-gap', calendar(
        'UID:s\nDTSTART;TZID=America/New_York:20260307T023000\nDTEND;TZID=America/New_York:20260307T033000\nRRULE:FREQ=DAILY;COUNT=4',
        'UID:s\nRECURRENCE-ID;TZID=America/New_York:20260309T023000\nDTSTART;TZID=America/New_York:20260309T050000\nDTEND;TZID=America/New_York:20260309T060000'), 'rfc_disagreement'
    yield 'fall-elapsed-duration', calendar(
        'UID:s\nDTSTART;TZID=America/New_York:20261031T013000\nDTEND;TZID=America/New_York:20261031T033000\nRRULE:FREQ=DAILY;COUNT=4',
        'UID:s\nRECURRENCE-ID;TZID=America/New_York:20261102T013000\nDTSTART;TZID=America/New_York:20261102T050000\nDTEND;TZID=America/New_York:20261102T060000'), 'duration_difference'


def normalized(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00','Z') if isinstance(value,datetime) else value.isoformat()


def compare():
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        for name, raw, classification in fixtures():
            source = Path(temp)/'synthetic.ics'
            source.write_bytes(raw)
            start,end = ('2026-10-30','2026-11-05') if name.startswith('fall') else ('2026-03-04','2026-03-12')
            ours = analyze([source],start,end,'UTC')
            assert ours['complete'], ours['issues']
            actual = sorted((o['start'],o['end']) for o in ours['occurrences'])
            other = recurring_ical_events.of(Calendar.from_ical(raw)).between(
                datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
                datetime.fromisoformat(end).replace(tzinfo=timezone.utc))
            reference = sorted((normalized(o['DTSTART'].dt),normalized(o['DTEND'].dt)) for o in other
                               if str(o.get('STATUS','')).upper() != 'CANCELLED' and str(o.get('TRANSP','')).upper() != 'TRANSPARENT')
            equal = actual == reference
            assert equal == (classification == 'agreement'), (name,actual,reference)
            rows.append({'fixture':name,'input_sha256':hashlib.sha256(raw).hexdigest(),
                         'classification':classification,'equal':equal,'audit':actual,'reference':reference})
    return {'dependencies':{n:metadata.version(n) for n in ['recurring-ical-events','icalendar','python-dateutil','tzdata','x-wr-timezone','click']},
            'normalization':'Compare effective start/end; filter reference CANCELLED/TRANSPARENT components explicitly.',
            'cases':rows}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = compare()
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(f'{len(result["cases"])} comparisons; '+str(sum(c['equal'] for c in result['cases']))+' agreements; remaining differences preserved.')
