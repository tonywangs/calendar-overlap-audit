"""Pair-free execution, dense independent endpoint oracle, and failure semantics."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
import random
from unittest.mock import patch

import pytest

from calendar_audit.availability import availability
from calendar_audit.availability_cli import main
from calendar_audit.core import AuditError, Budget, Limits, analyze
from calendar_audit.availability_report import html_bytes
from calendar_audit.report import json_bytes
from test_availability import SPEC, timed, stamp
from conftest import FIXTURES


@pytest.mark.parametrize('seed', range(12))
def test_dense_independent_endpoint_oracle(seed, make_ics, baseline_availability):
    rng = random.Random(20261001 + seed)
    lo = datetime(2026, 3, 6, 9, tzinfo=timezone.utc)
    events, expected = [], []
    # >20,000 overlaps from the tied core alone, plus nesting, adjacency, zero
    # duration, moved/cancelled/transparent overrides and two distinct sources.
    for i in range(240):
        a, b = rng.choice([(3600,7200), (3600,5400), (4000,6000), (4500,7200)])
        events.append(timed(f'core-{i}', lo+timedelta(seconds=a), lo+timedelta(seconds=b)))
        expected.append((a,b))
    for i,(a,b) in enumerate([(7200,9000),(9000,9000),(12600,14400),(12600,14400),(-3600,0),(28800,30000)]):
        events.append(timed(f'edge-{i}', lo+timedelta(seconds=a),lo+timedelta(seconds=b)) if a != b else f'UID:edge-{i}\nDTSTART:{stamp(lo+timedelta(seconds=a))}')
        if max(a,0) < min(b,28800):
            expected.append((max(a,0),min(b,28800)))
    original = lo + timedelta(seconds=18000)
    for mode in ('moved', 'cancelled', 'transparent'):
        events.append(timed(mode, original,original+timedelta(seconds=1800),'RRULE:FREQ=DAILY;COUNT=2'))
        extra = {'moved':f'DTSTART:{stamp(lo+timedelta(seconds=21600))}',
                 'cancelled':'STATUS:CANCELLED',
                 'transparent':f'DTSTART:{stamp(original)}\nTRANSP:TRANSPARENT'}[mode]
        events.append(f'UID:{mode}\nRECURRENCE-ID:{stamp(original)}\n{extra}')
    expected.append((21600,23400))
    # Keep each UID family together; ordering varies to exercise stable ID links.
    core = events[:240]
    rng.shuffle(core)
    events[:240] = core
    paths = [make_ics(*events[:120],name='first.ics'),make_ics(*events[120:],name='second.ics')]
    before = [p.read_bytes() for p in paths]
    with pytest.raises(baseline_availability.__globals__['AuditError'], match='pairs limit exceeded'):
        baseline_availability(paths, SPEC)
    budget = Budget(Limits(pairs=1))
    with patch('calendar_audit.core.overlap_pairs',side_effect=AssertionError('pairs called')):
        r = availability(paths,SPEC,limits=budget.limits,budget=budget)
    assert r['complete'] and 'pairs' not in budget.counts, r['audit']['issues']
    assert 'overlaps' not in r['audit'] and 'pairs' not in r['limits']
    # Independent elementary-segment oracle: test occupancy on each interval
    # between input boundaries, then concatenate consecutive uncovered segments.
    points = sorted({0,28800,*[x for a,b in expected for x in (a,b)]})
    gaps, occupied_segments = [], []
    for a,b in zip(points,points[1:]):
        if not any(x <= a and b <= y for x,y in expected):
            if gaps and gaps[-1][1] == a:
                gaps[-1] = (gaps[-1][0],b)
            else:
                gaps.append((a,b))
        elif occupied_segments and occupied_segments[-1][1] == a:
            occupied_segments[-1] = (occupied_segments[-1][0],b)
        else:
            occupied_segments.append((a,b))
    gaps = [(a,b) for a,b in gaps if b-a >= SPEC['minimum_seconds']]
    def offset(raw):
        return int((datetime.fromisoformat(raw)-lo).total_seconds())
    assert [(offset(g['start']),offset(g['end'])) for g in r['candidates']] == gaps
    occurrences = r['audit']['occurrences']
    assert len(occurrences) == 247 and len(r['audit']['cancellations']) == 1
    clipped = [(max(0,offset(o['start'])),min(28800,offset(o['end'])),o['id']) for o in occurrences]
    clipped = [(a,b,i) for a,b,i in clipped if a < b]
    assert sorted((a,b) for a,b,_ in clipped) == sorted(expected)
    blocks = r['windows'][0]['busy']
    assert [(offset(b['start']),offset(b['end'])) for b in blocks] == occupied_segments
    for block,(a,b) in zip(blocks,occupied_segments):
        assert block['occurrences'] == sorted(i for x,y,i in clipped if a <= x < y <= b)
        assert block['start_occurrences'] == sorted(i for x,y,i in clipped if x == a)
        assert block['end_occurrences'] == sorted(i for x,y,i in clipped if y == b)
    for g,(a,b) in zip(r['candidates'],gaps):
        left = sorted(o['id'] for o in occurrences if offset(o['end']) == a and offset(o['start']) < a) if a else []
        right = sorted(o['id'] for o in occurrences if offset(o['start']) == b and offset(o['end']) > b) if b < 28800 else []
        assert (g['before'],g['after']) == (left,right)
    again = availability(paths,SPEC,limits=budget.limits)
    assert json_bytes(r) == json_bytes(again)
    assert html_bytes(r,Budget(Limits())) == html_bytes(again,Budget(Limits()))
    assert before == [p.read_bytes() for p in paths]


@pytest.mark.parametrize('fixture', ['synthetic.ics','overrides.ics','dst-spring.ics','dst-fall.ics','weekly.ics'])
def test_fixtures_semantic_equivalence(fixture,baseline_availability):
    from baseline import semantics
    spec = {**SPEC,'start':'2026-03-01','end':'2026-03-15','timezone':'America/New_York'}
    paths = [FIXTURES/fixture]
    assert semantics(availability(paths,spec)) == semantics(baseline_availability(paths,spec))


@pytest.mark.parametrize('kind',['unsupported','orphan','conflicting_snapshots','duplicate_snapshots','cancelled','transparent'])
def test_diagnostics_and_source_boundaries(kind,make_ics,baseline_availability):
    event = 'UID:a\nDTSTART:20260306T100000Z\nDTEND:20260306T110000Z'
    extra = {'unsupported':'\nRRULE:FREQ=MONTHLY','orphan':'\nRECURRENCE-ID:20260306T100000Z',
             'cancelled':'\nSTATUS:CANCELLED','transparent':'\nTRANSP:TRANSPARENT'}.get(kind,'')
    paths = [make_ics(event+extra,name='a.ics')]
    if kind.endswith('snapshots'):
        paths.append(make_ics(event+('\nSUMMARY:changed' if kind.startswith('conflicting') else ''),name='b.ics'))
    from baseline import semantics
    r = availability(paths,SPEC)
    assert semantics(r) == semantics(baseline_availability(paths,SPEC))
    if kind in ('unsupported','orphan','conflicting_snapshots'):
        assert not r['complete'] and r['candidates'] == [] and r['candidate_seconds'] is None


@pytest.mark.parametrize('field', ['files','input_bytes','line_bytes','events','candidates','resolutions','occurrences'])
def test_applicable_expansion_limits(field,make_ics):
    events = ['UID:a\nDTSTART:20260305T100000Z\nDTEND:20260305T110000Z\nRRULE:FREQ=DAILY;COUNT=3',
              'UID:a\nRECURRENCE-ID:20260306T100000Z\nDTSTART:20260306T120000Z',
              'UID:b\nDTSTART:20260305T130000Z\nDTEND:20260305T140000Z\nRRULE:FREQ=DAILY;COUNT=3']
    paths = [make_ics(*events,name='a.ics'),make_ics(name='b.ics')]
    spec = {**SPEC, 'start':'2026-03-05'}
    limits = replace(Limits(), **{field:1})
    if field == 'resolutions':
        r = availability(paths,spec,limits)
        assert not r['complete'] and not r['candidates'] and r['candidate_seconds'] is None
        assert any(i['code']=='resolution_limit' for i in r['audit']['issues'])
    else:
        with pytest.raises(AuditError,match=field+' limit exceeded'):
            availability(paths,spec,limits)


def test_deadline_checked_after_expansion(make_ics):
    from calendar_audit.core import analyze_occurrences
    p = make_ics()
    budget = Budget(Limits())
    def expire(*args,**kwargs):
        result = analyze_occurrences(*args,**kwargs)
        budget.started -= 60
        return result
    with patch('calendar_audit.availability.analyze_occurrences',side_effect=expire):
        with pytest.raises(AuditError,match='Execution-time limit exceeded'):
            availability([p],SPEC,budget=budget)


def test_dense_cli_legacy_and_no_pair_claim(tmp_path,make_ics):
    p = make_ics(*[f'UID:{i}\nDTSTART:20260306T100000Z\nDTEND:20260306T110000Z' for i in range(250)])
    spec = tmp_path/'spec.json'; spec.write_text(json.dumps(SPEC))
    args = [str(p),'--spec',str(spec),'--output',str(tmp_path/'out')]
    assert main(args+['--max-pairs','1']) == 0
    report = json.loads((tmp_path/'out/report.json').read_text())
    assert report['schema_version'] == 2 and report['candidate_seconds'] == 7*3600
    page = (tmp_path/'out/report.html').read_text()
    assert 'Overlap pairs were not computed' in page
    assert 'No overlapping timed pairs' not in page and '0 overlap pairs' not in page
    assert main(args[:-1]+[str(tmp_path/'legacy'),'--include-overlaps']) == 2
    assert not (tmp_path/'legacy').exists()
    with pytest.raises(AuditError,match='pairs limit exceeded'):
        analyze([p],SPEC['start'],SPEC['end'],'UTC')
