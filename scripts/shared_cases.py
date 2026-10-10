"""Synthetic fixtures and independent second-cell oracle; no production imports."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random

UTC = timezone.utc
BASE = datetime(2026, 3, 9, 9, tzinfo=UTC)  # Monday
SEED = 55451000


def stamp(value):
    return value.strftime('%Y%m%dT%H%M%SZ')


def text(value):
    return value.isoformat().replace('+00:00', 'Z')


def ics(lo, hi, periods=(), metadata=''):
    properties = []
    for a, b, kind, by_duration in periods:
        end = 'PT'+str(int((b-a).total_seconds()))+'S' if by_duration else stamp(b)
        properties.append(f'FREEBUSY;FBTYPE={kind}:{stamp(a)}/{end}')
    return ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Synthetic shared windows//EN\r\n'
            'BEGIN:VFREEBUSY\r\nUID:synthetic-only\r\nDTSTAMP:20261010T010000Z\r\n'
            f'DTSTART:{stamp(lo)}\r\nDTEND:{stamp(hi)}\r\n'+
            '\r\n'.join(properties)+ ('\r\n' if properties else '') +
            (metadata+'\r\n' if metadata else '') + 'END:VFREEBUSY\r\nEND:VCALENDAR\r\n').encode()


def person(alias, sources, weekly=None, zone='UTC'):
    return dict(alias=alias, timezone=zone,
                weekly={'MO':[['09:00','10:00']]} if weekly is None else weekly,
                sources=[dict(path=s, complete_occupancy=True) for s in sources])


def manifest(participants, lo=BASE, hi=BASE+timedelta(hours=1), minimum=60):
    return dict(version=1, start=text(lo), end=text(hi), duration_seconds=minimum, participants=participants)


def write_case(directory, spec, raws):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, raw in raws.items():
        (directory/name).write_bytes(raw)
    path = directory/'manifest.json'
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=True)+'\n')
    return path


def runs(cells, lo=BASE, minimum=1):
    """Run-length encoding of independently enumerated occupied one-second cells."""
    result, start = [], None
    for index, value in enumerate([*cells, False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if index-start >= minimum:
                result.append((lo+timedelta(seconds=start), lo+timedelta(seconds=index)))
            start = None
    return result


def seeded(seed):
    """Enumerate each second, never use production set algorithms or parser."""
    rng = random.Random(seed)
    n = rng.randint(1, 5)
    horizon = 600
    all_free = [True]*horizon
    expected_people, raws, people = [], {}, []
    for p in range(n):
        coverage = [False]*horizon
        busy = [False]*horizon
        names = []
        for s in range(rng.randint(1, 3)):
            ca = rng.randrange(-30, horizon+30)
            cb = rng.randrange(ca+1, horizon+61)
            for t in range(max(0, ca), min(horizon, cb)):
                coverage[t] = True
            periods = []
            for _ in range(rng.randrange(10)):
                a = rng.randrange(ca, cb)
                b = rng.randrange(a+1, cb+1)
                kind = rng.choice(['BUSY','BUSY-TENTATIVE','BUSY-UNAVAILABLE','FREE'])
                periods.append((BASE+timedelta(seconds=a),BASE+timedelta(seconds=b),kind,rng.choice([True,False])))
                if kind != 'FREE':
                    for t in range(max(0,a), min(horizon,b)):
                        busy[t] = True
            if periods and rng.choice([True,False]):
                periods.append(periods[0])  # duplicates do not alter the oracle
            rng.shuffle(periods)
            name=f'p{p}s{s}.ics'
            names.append(name)
            raws[name]=ics(BASE+timedelta(seconds=ca),BASE+timedelta(seconds=cb),periods)
        work = [False]*horizon
        windows = []
        for _ in range(rng.randrange(1,5)):
            a = rng.randrange(0,10)
            b = rng.randrange(a+1,11)
            windows.append([f'09:{a:02}',f'09:{b:02}'])
            for t in range(a*60,b*60):
                work[t]=True
        free = [c and w and not b for c,w,b in zip(coverage,work,busy)]
        all_free = [a and b for a,b in zip(all_free,free)]
        expected_people.append(dict(coverage=runs(coverage),coverage_gaps=runs([not v for v in coverage]),
                                    busy=runs(busy),working=runs(work),free=runs(free)))
        people.append(person(f'Participant {p+1}',names,{'MO':windows}))
    minimum=rng.choice([1,2,30,59,60,61,120,600,601])
    return manifest(people,hi=BASE+timedelta(seconds=horizon),minimum=minimum),raws,runs(all_free,minimum=minimum),expected_people


def decode_independently(raw):
    from icalendar import Calendar
    cal=Calendar.from_ical(raw)
    fb=cal.walk('VFREEBUSY')[0]
    periods=fb.get('FREEBUSY',[])
    if not isinstance(periods,list):
        periods=[periods]
    blocks=[]
    counts=dict(BUSY=0,**{'BUSY-TENTATIVE':0,'BUSY-UNAVAILABLE':0,'FREE':0})
    for period in periods:
        kind=str(period.params.get('FBTYPE','BUSY')).upper()
        counts[kind]+=1
        if kind!='FREE':
            blocks.append((period.start,period.end))
    return (fb.decoded('DTSTART'),fb.decoded('DTEND')),blocks,counts
