"""Coverage semantics, independent parser and seeded second-cell set oracle."""
from dataclasses import fields
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

from calendar_audit.core import AuditError, Budget
from calendar_audit.shared import discover
from calendar_audit.shared_input import SharedLimits, parse_freebusy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from shared_cases import BASE, SEED, decode_independently, ics, manifest, person, seeded, stamp, write_case


def pairs(items):
    return [(datetime.fromisoformat(i['start']),datetime.fromisoformat(i['end'])) for i in items]


def parse(raw, **kwargs):
    return parse_freebusy(raw,Budget(SharedLimits(**kwargs)))


@pytest.mark.parametrize('seed', range(SEED,SEED+512))
def test_seeded_cells_and_independent_reader(tmp_path,seed):
    spec,raws,expected,people=seeded(seed)
    before=dict(raws)
    path=write_case(tmp_path,spec,raws)
    report=discover(path)
    assert report['complete']
    assert pairs(report['windows'])==expected
    assert report['window_seconds']==sum(int((b-a).total_seconds()) for a,b in expected)
    for actual,expected_person in zip(report['participants'],people):
        for key,value in expected_person.items():
            assert pairs(actual[key])==value, (seed,key)
    for name,raw in raws.items():
        assert parse(raw)==decode_independently(raw)
        assert (tmp_path/name).read_bytes()==before[name]


def simple(tmp_path,periods=(),minimum=60,lo=BASE,hi=BASE+timedelta(hours=1),weekly=None,zone='UTC'):
    return write_case(tmp_path,manifest([person('A',['a.ics'],weekly,zone)],lo,hi,minimum),{'a.ics':ics(lo,hi,periods)})


@pytest.mark.parametrize('minimum,count',[(3599,1),(3600,1),(3601,0)])
def test_empty_and_duration_boundary(tmp_path,minimum,count):
    report=discover(simple(tmp_path,minimum=minimum))
    assert len(report['windows'])==count and report['coverage_complete']
    if count:
        assert report['windows'][0]['seconds']==3600
        assert datetime.fromisoformat(report['windows'][0]['latest_start'])==BASE+timedelta(seconds=3600-minimum)


def test_union_busy_wins_adjacent_and_conflicting_files(tmp_path):
    lo,hi=BASE,BASE+timedelta(hours=1)
    a,b,c=lo+timedelta(minutes=10),lo+timedelta(minutes=20),lo+timedelta(minutes=30)
    raws={'a.ics':ics(lo,hi,[(a,b,'BUSY',False),(b,c,'BUSY-TENTATIVE',True),(a,b,'BUSY',True)]),
          'b.ics':ics(lo,hi,[(lo,hi,'FREE',True)])}
    spec=manifest([person('A',list(raws))],minimum=1)
    result=discover(write_case(tmp_path,spec,raws))
    assert pairs(result['participants'][0]['busy'])==[(a,c)]
    assert pairs(result['windows'])==[(lo,a),(c,hi)]


def test_disjoint_coverage_between_people(tmp_path):
    middle=BASE+timedelta(minutes=30)
    path=write_case(tmp_path,manifest([person('A',['a.ics']),person('B',['b.ics'])]),
                    {'a.ics':ics(BASE,middle),'b.ics':ics(middle,BASE+timedelta(hours=1))})
    result=discover(path)
    assert result['windows']==[] and not result['coverage_complete'] and result['complete']
    assert len(result['participants'][0]['coverage_gaps'])==1


def test_coverage_union_keeps_unknown_hole(tmp_path):
    a,b=BASE+timedelta(minutes=20),BASE+timedelta(minutes=40)
    path=write_case(tmp_path,manifest([person('A',['a.ics','b.ics'])]),
                    {'a.ics':ics(BASE,a),'b.ics':ics(b,BASE+timedelta(hours=1))})
    result=discover(path)
    assert pairs(result['participants'][0]['coverage_gaps'])==[(a,b)]
    assert len(result['windows'])==2


def test_outside_coverage_not_free(tmp_path):
    path=write_case(tmp_path,manifest([person('A',['a.ics'])]),{'a.ics':ics(BASE-timedelta(days=1),BASE)})
    result=discover(path)
    assert result['windows']==[] and result['participants'][0]['coverage']==[]
    assert result['participants'][0]['coverage_gaps']==[result['horizon']]


@pytest.mark.parametrize('date,expected_hours', [('2026-03-08',3),('2026-11-01',5)])
def test_dst_crossing_overnight(tmp_path,date,expected_hours):
    day=datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    lo,hi=day,day+timedelta(days=1)
    path=simple(tmp_path,lo=lo,hi=hi,weekly={'SA':[['23:00','03:00']]},zone='America/New_York')
    r=discover(path)
    assert len(r['windows'])==1 and r['windows'][0]['seconds']==expected_hours*3600
    assert r['windows'][0]['local'][0]['start'].startswith((day-timedelta(days=1)).date().isoformat()+'T23:00')


@pytest.mark.parametrize('date,clock,kind',[('2026-03-08','02:30','Nonexistent'),('2026-11-01','01:30','Ambiguous')])
def test_dst_ambiguous_nonexistent_rejected(tmp_path,date,clock,kind):
    lo=datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    path=simple(tmp_path,lo=lo,hi=lo+timedelta(days=1),weekly={'SU':[[clock,'04:00']]},zone='America/New_York')
    with pytest.raises(AuditError,match=kind):
        discover(path)


def test_previous_day_overnight_spill_and_adjacent_work(tmp_path):
    lo=BASE.replace(hour=0)
    path=simple(tmp_path,lo=lo,hi=lo+timedelta(hours=4),weekly={'SU':[['23:00','02:00']],'MO':[['02:00','04:00']]})
    result=discover(path)
    assert len(result['windows'])==1 and result['windows'][0]['seconds']==14400


def test_sixteen_people_and_ninety_days(tmp_path):
    hi=BASE+timedelta(days=90)
    people=[person(str(i),[f'{i}.ics'],{d:[['00:00','24:00']] for d in ['MO','TU','WE','TH','FR','SA','SU']}) for i in range(16)]
    report=discover(write_case(tmp_path,manifest(people,hi=hi),{f'{i}.ics':ics(BASE,hi) for i in range(16)}))
    assert len(report['windows'])==1 and report['windows'][0]['seconds']==90*86400
    assert len(report['windows'][0]['local'])==16


@pytest.mark.parametrize('duration', ['PT1S','+PT60S','PT1H30M','P1D','P1DT2H3M4S','P1W','P0DT1S'])
def test_duration_grammar_independent(duration):
    lo,hi=BASE,BASE+timedelta(days=9)
    raw=ics(lo,hi).replace(b'END:VFREEBUSY',f'FREEBUSY:{stamp(lo)}/{duration}\r\nEND:VFREEBUSY'.encode())
    assert parse(raw)==decode_independently(raw)


@pytest.mark.parametrize('period',[
    '20260309T090000Z/20260309T090000Z','20260309T090000Z/20260309T080000Z',
    '20260309T090000Z/PT0S','20260309T090000Z/-PT1H','20260309T090000Z/P',
    '20260309T090000Z/PT','20260309T090000Z/P1DT','20260309T090000Z/P1M',
    '20260309T090000Z/P1Y','20260309T090000Z/P1W1D','20260309T090000Z/PT1.5H',
    '20260309T090000Z/PT1M2H','20260309T090000Z/PT100000000000000000S',
    '20260309T090000Z/20260309T110000Z','20260309T085959Z/PT1S',
    '20260309T090000/PT1S','20260309/PT1H','20260309T090000+0000/PT1H',
    '20260230T090000Z/PT1H','20260309T090060Z/PT1H','20260309T090000Z//PT1S','',
    '20260309T090000Z/PT1S,','20260309T090000Z/PT1S,,20260309T090001Z/PT1S',
    '20260309T090000Z/PT١S','20260309T090000Z/pt1s',
    '99991231T235959Z/PT1S',
])
def test_bad_periods(period):
    raw=ics(BASE,BASE+timedelta(hours=1)).replace(b'END:VFREEBUSY',f'FREEBUSY:{period}\r\nEND:VFREEBUSY'.encode())
    with pytest.raises(AuditError): parse(raw)


@pytest.mark.parametrize('extra',[
    'FREEBUSY;FBTYPE=X-MAYBE:20260309T090000Z/PT1S',
    'FREEBUSY;FBTYPE=BUSY;FBTYPE=FREE:20260309T090000Z/PT1S',
    'FREEBUSY;VALUE=DATE-TIME:20260309T090000Z/PT1S',
    'FREEBUSY;TZID=UTC:20260309T090000Z/PT1S',
    'RRULE:FREQ=DAILY','RDATE:20260309T090000Z','EXDATE:20260309T090000Z',
    'ATTENDEE:mailto:private@example.invalid','REQUEST-STATUS:2.0;OK','SUMMARY:PRIVATE',
    'UID:duplicate','DTSTART:20260309T090000Z','DTEND;VALUE=DATE:20260310',
    'X-UNKNOWN:PRIVATE','COMMENT;LANGUAGE=en:PRIVATE',
])
def test_unsupported_properties(extra):
    raw=ics(BASE,BASE+timedelta(hours=1),metadata=extra)
    with pytest.raises(AuditError): parse(raw)


@pytest.mark.parametrize('old,new',[
    (b'DTSTART:20260309T090000Z\r\n',b''),(b'DTEND:20260309T100000Z\r\n',b''),
    (b'UID:synthetic-only\r\n',b''),(b'DTSTAMP:20261010T010000Z\r\n',b''),
    (b'VERSION:2.0',b'VERSION:1.0'),(b'VERSION:2.0',b'VERSION:2.0\r\nMETHOD:REQUEST'),
    (b'VERSION:2.0',b'VERSION:2.0\r\nMETHOD:REPLY'),
    (b'VERSION:2.0',b'VERSION:2.0\r\nCALSCALE:PRIVATE'),
    (b'END:VCALENDAR',b'END:VFREEBUSY'),(b'BEGIN:VFREEBUSY',b'BEGIN:VEVENT'),
    (b'END:VFREEBUSY',b'BEGIN:VALARM\r\nEND:VALARM\r\nEND:VFREEBUSY'),
    (b'END:VCALENDAR',b'BEGIN:VFREEBUSY\r\nEND:VFREEBUSY\r\nEND:VCALENDAR'),
    (b'PRODID:',b'PRODID:\x00'),(b'PRODID:',b'PRODID:\xff'),
    (b'UID:',b'UID:\r'),(b'UID:',b'\r\nUID:'),
])
def test_structural_rejections(old,new):
    with pytest.raises(AuditError): parse(ics(BASE,BASE+timedelta(hours=1)).replace(old,new))


def test_folding_parameters_and_metadata_exclusion(tmp_path):
    raw=ics(BASE,BASE+timedelta(hours=1),metadata='COMMENT:</script><img src=https://private.invalid/>')
    raw=raw.replace(b'END:VFREEBUSY',b'FREEBUSY;fbtype="busy";VALUE=PERIOD:20260309T091000Z/PT60S,\r\n\t20260309T092000Z/PT60S\r\nEND:VFREEBUSY')
    assert parse(raw)==decode_independently(raw)
    raw=raw.replace(b'DTSTART:',b'DTSTART;VALUE=DATE-TIME:')
    path=write_case(tmp_path,manifest([person('A',['a.ics'])]),{'a.ics':raw})
    report=discover(path)
    assert 'private.invalid' not in json.dumps(report)
    assert 'synthetic-only' not in json.dumps(report)


@pytest.mark.parametrize('field', ['version','duration_seconds','participants','start','end'])
def test_missing_manifest_fields(tmp_path,field):
    spec=manifest([person('A',['a.ics'])]); del spec[field]
    with pytest.raises(AuditError): discover(write_case(tmp_path,spec,{'a.ics':ics(BASE,BASE+timedelta(hours=1))}))


@pytest.mark.parametrize('change',[
    lambda s:s.update(version=True),lambda s:s.update(version=2),
    lambda s:s.update(duration_seconds=True),lambda s:s.update(duration_seconds=0),
    lambda s:s.update(duration_seconds=1.5),lambda s:s.update(participants=[]),
    lambda s:s.update(end='2027-01-01T00:00:00Z'),
    lambda s:s['participants'][0].update(alias='\x00PRIVATE'),
    lambda s:s['participants'][0].update(timezone='../PRIVATE'),
    lambda s:s['participants'][0].update(sources=[]),
    lambda s:s['participants'][0]['sources'][0].update(complete_occupancy=False),
    lambda s:s['participants'][0]['sources'][0].update(complete_occupancy=1),
    lambda s:s['participants'][0]['sources'][0].update(path='https://private.invalid/a.ics'),
    lambda s:s['participants'][0].update(weekly={'XX':[]}),
    lambda s:s['participants'][0].update(weekly={'MO':[['09:00','09:00']]}),
    lambda s:s['participants'][0].update(weekly={'MO':[['24:00','01:00']]}),
    lambda s:s['participants'][0].update(weekly={'MO':[['9:00','10:00']]}),
    lambda s:s['participants'][0].update(weekly={'MO':[['09:00','10:00']]*17}),
    lambda s:s.update(participants=s['participants']*17),
    lambda s:s['participants'][0].update(sources=s['participants'][0]['sources']*33),
])
def test_invalid_manifest_values(tmp_path,change):
    spec=manifest([person('A',['a.ics'])]);change(spec)
    with pytest.raises((AuditError,ValueError)):
        discover(write_case(tmp_path,spec,{'a.ics':ics(BASE,BASE+timedelta(hours=1))}))


@pytest.mark.parametrize('field', [f.name for f in fields(SharedLimits)])
@pytest.mark.parametrize('value',[0,-1,True,float('nan'),float('inf'),'1'])
def test_strict_limit_types(field,value):
    with pytest.raises(AuditError): SharedLimits(**{field:value})


def test_same_file_reassigned_to_another_person(tmp_path):
    path=write_case(tmp_path,manifest([person('A',['a.ics']),person('B',['link.ics'])]),{'a.ics':ics(BASE,BASE+timedelta(hours=1))})
    (tmp_path/'link.ics').symlink_to('a.ics')
    with pytest.raises(AuditError,match='owners'): discover(path)


def test_bare_cr_at_end_and_properties_after_component():
    raw=ics(BASE,BASE+timedelta(hours=1))
    with pytest.raises(AuditError): parse(raw[:-1])
    late=raw.replace(b'VERSION:2.0\r\n',b'').replace(b'END:VCALENDAR',b'VERSION:2.0\r\nEND:VCALENDAR')
    with pytest.raises(AuditError): parse(late)


def test_byte_fold_inside_unicode_and_lf_support():
    raw=ics(BASE,BASE+timedelta(hours=1),metadata='COMMENT:café')
    assert parse(raw)==parse(raw.replace(b'\xc3\xa9',b'\xc3\r\n \xa9'))
    assert parse(raw)==parse(raw.replace(b'\r\n',b'\n'))


def test_unfolded_line_limit_cannot_be_bypassed():
    raw=ics(BASE,BASE+timedelta(hours=1),metadata='COMMENT:'+('a'*20+'\r\n ')*10+'z')
    with pytest.raises(AuditError,match='line_bytes'): parse(raw,line_bytes=100)


def test_actual_period_ceiling_counts_free_and_duplicates():
    raw=ics(BASE,BASE+timedelta(hours=1),[(BASE,BASE+timedelta(seconds=1),'FREE',True)]*20001)
    with pytest.raises(AuditError,match='periods'): parse(raw)


def test_free_only_cannot_extend_coverage(tmp_path):
    end=BASE+timedelta(minutes=20)
    raw=ics(BASE,end,[(BASE,end,'FREE',True)])
    result=discover(write_case(tmp_path,manifest([person('A',['a.ics'])]),{'a.ics':raw}))
    assert pairs(result['windows'])==[(BASE,end)]
    assert result['participants'][0]['sources'][0]['period_counts']['FREE']==1


def test_optional_standard_params_and_case_insensitivity():
    raw=ics(BASE,BASE+timedelta(hours=1))
    raw=raw.replace(b'VERSION:2.0',b'VERSION:2.0\r\nMETHOD:PUBLISH\r\nCALSCALE:GREGORIAN')
    raw=raw.replace(b'END:VFREEBUSY',b'freebusy;fbtype=busy:20260309T090000Z/20260309T090001Z\r\nEND:VFREEBUSY')
    assert parse(raw)==decode_independently(raw)


def test_lowercase_utc_markers_rejected_by_both_readers():
    raw=ics(BASE,BASE+timedelta(hours=1)).replace(b'END:VFREEBUSY',
        b'FREEBUSY:20260309t090000z/20260309t090001z\r\nEND:VFREEBUSY')
    with pytest.raises(AuditError): parse(raw)
    with pytest.raises(ValueError): decode_independently(raw)


def test_half_open_adjacent_busy_and_period_seconds(tmp_path):
    raw=ics(BASE,BASE+timedelta(hours=1),[(BASE,BASE+timedelta(seconds=3599),'BUSY',False)])
    spec=manifest([person('A',['a.ics'])],minimum=1)
    result=discover(write_case(tmp_path,spec,{'a.ics':raw}))
    assert len(result['windows'])==1 and result['windows'][0]['seconds']==1
    assert result['windows'][0]['start']==result['windows'][0]['latest_start']


@pytest.mark.parametrize('old,new',[(b'DTSTART','DTſTART'.encode()),
    (b'VFREEBUSY','VFREEBUſY'.encode()),(b'VERSION:2.0','VERSION:2.0\r\nMETHOD:PUBLIſH'.encode())])
def test_non_ascii_identifier_case_mapping_is_rejected(old,new):
    with pytest.raises(AuditError):parse(ics(BASE,BASE+timedelta(hours=1)).replace(old,new))
