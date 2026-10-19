#!/usr/bin/env python3
"""Offline wheel installation, independent real-input oracle, and Chromium workflow.

Oracle intentionally uses no calendar_audit or icalendar code: it accepts only the
frozen exports' simple floating intervals and uses published CET/EST/JST offsets.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'examples/public-fosdem'
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.cache/ms-playwright'))


def run(args, **kw):
    subprocess.run([str(a) for a in args], check=True, **kw)


def raw_intervals():
    provenance = json.loads((DATA / 'provenance.json').read_text())
    intervals = {}
    for item in provenance['files']:
        raw = (DATA / item['file']).read_bytes()
        assert len(raw) == item['bytes']
        assert hashlib.sha256(raw).hexdigest() == item['sha256']
        text = raw.decode().replace('\r\n', '\n')
        # This deliberately fails if the preserved fixture stops being this subset.
        assert not re.search(r'^(RRULE|RDATE|EXDATE|RECURRENCE-ID|DURATION|TRANSP|STATUS:CANCELLED)', text, re.M)
        events = re.findall(r'BEGIN:VEVENT\n(.*?)END:VEVENT', text, re.S)
        assert len(events) == text.count('BEGIN:VEVENT')
        for event in events:
            uid = re.findall(r'^UID:(.+)$', event, re.M)
            start = re.findall(r'^DTSTART:(\d{8}T\d{6})$', event, re.M)
            end = re.findall(r'^DTEND:(\d{8}T\d{6})$', event, re.M)
            assert len(uid) == len(start) == len(end) == 1
            assert uid[0] not in intervals
            # Official schedule states CET (UTC+1). February 2025: no DST transition.
            a, b = [datetime.strptime(x[0], '%Y%m%dT%H%M%S').replace(tzinfo=timezone(timedelta(hours=1))) for x in (start, end)]
            assert a < b and a.date().isoformat() == '2025-02-01'
            intervals[uid[0]] = (a, b)
    assert len(intervals) == 24
    return intervals


def oracle(report, intervals, offset):
    assert report['complete'] and not report['issues']
    assert report['floating_timezone'] == 'Europe/Brussels'
    events = {e['id']: e['uid'] for e in report['events']}
    occurrences = {o['id']: o for o in report['occurrences']}
    assert len(occurrences) == len(intervals)
    seen = set()
    occupied = set()
    target = timezone(timedelta(hours=offset))
    for o in occurrences.values():
        uid = events[o['event']]
        assert uid not in seen
        seen.add(uid)
        a, b = intervals[uid]
        assert datetime.fromisoformat(o['start'].replace('Z', '+00:00')) == a
        assert datetime.fromisoformat(o['end'].replace('Z', '+00:00')) == b
        assert o['local_start'] == a.astimezone(target).isoformat()
        assert o['local_end'] == b.astimezone(target).isoformat()
        occupied.update(range(int(a.timestamp()), int(b.timestamp())))
    assert seen == set(intervals)
    # Enumerate seconds, not the production interval-union algorithm.
    assert report['occupied_seconds'] == len(occupied) == 27900
    daily = {}
    for second in occupied:
        day = datetime.fromtimestamp(second, target).date().isoformat()
        daily[day] = daily.get(day, 0) + 1
    assert {d['date']: d['occupied_seconds'] for d in report['daily']} == {
        day: daily.get(day, 0) for day in ('2025-02-01', '2025-02-02')}
    expected = {}
    for (uid, (a, b)), (other, (c, d)) in itertools.combinations(intervals.items(), 2):
        seconds = int((min(b, d) - max(a, c)).total_seconds())
        if seconds > 0:
            expected[tuple(sorted((uid, other)))] = seconds
    actual = {}
    for pair in report['overlaps']:
        uids = tuple(sorted(events[occurrences[pair[key]]['event']] for key in ('left', 'right')))
        assert uids not in actual
        actual[uids] = pair['seconds']
        a, b = intervals[uids[0]]
        c, d = intervals[uids[1]]
        assert datetime.fromisoformat(pair['start'].replace('Z', '+00:00')) == max(a, c)
        assert datetime.fromisoformat(pair['end'].replace('Z', '+00:00')) == min(b, d)
    assert actual == expected and len(actual) == 8
    print(f"Independent oracle: {report['window']['timezone']}: {daily}, 8 pairs", flush=True)


def browser_check(path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(offline=True, service_workers='block', viewport={'width': 1280, 'height': 900})
        requests, errors = [], []
        def block(route):
            requests.append(route.request.url)
            route.abort()
        context.route('http://**/*', block)
        context.route('https://**/*', block)
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(path.as_uri())
        assert page.locator('[data-occurrence]:visible').count() == 24
        assert page.locator('[data-pair]:visible').count() == 8
        assert 'not your personal commitments' in page.locator('body').inner_text()
        assert 'Europe/Brussels' in page.locator('body').inner_text()
        page.keyboard.press('Tab')
        assert page.locator(':focus').inner_text() == 'Skip to report'
        page.keyboard.press('Enter')
        assert page.url.endswith('#main')
        page.locator('#search').fill('FreeBSD security audits')
        assert page.locator('[data-occurrence]:visible').count() == 1
        pair_link = page.locator('[data-pair]:visible a').first
        target = pair_link.get_attribute('href')
        pair_link.focus()
        page.keyboard.press('Enter')
        assert page.url.endswith(target)
        page.locator(target + ' a').first.click()
        assert re.search(r'#e\d+$', page.url)
        page.locator(page.url[page.url.index('#'):] + ' a[href^="#o"]').first.click()
        assert re.search(r'#o\d+$', page.url)
        page.keyboard.press('Escape')
        assert page.locator('[data-occurrence]:visible').count() == 24
        page.locator('#source').select_option('s1')
        assert page.locator('[data-occurrence]:visible').count() == 8
        page.get_by_role('button', name='Clear filters').click()
        assert page.locator('[data-occurrence]:visible').count() == 24
        assert page.evaluate("() => [...document.querySelectorAll('a')].every(a => a.hash && document.getElementById(a.hash.slice(1)))")
        assert not requests and not errors
        # Optional visual evidence goes only where explicitly requested.
        if os.environ.get('PUBLIC_REPORT_SCREENSHOT'):
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=os.environ['PUBLIC_REPORT_SCREENSHOT'])
        context.close()
        context = browser.new_context(offline=True, java_script_enabled=False)
        page = context.new_page()
        page.goto(path.as_uri())
        assert page.locator('[data-occurrence]:visible').count() == 24
        assert page.locator('noscript').is_visible()
        browser.close()
    print('Chromium: search, source filter, keyboard links/backreferences, reset, offline and no-JS passed', flush=True)


def main():
    intervals = raw_intervals()
    with tempfile.TemporaryDirectory(prefix='calendar-public-') as temporary:
        base = Path(temporary)
        wheels = base / 'wheels'
        wheels.mkdir()
        run([sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-deps', '--no-build-isolation', '--wheel-dir', wheels, ROOT], cwd=base)
        installed = base / 'installed'
        venv.EnvBuilder(with_pip=False).create(installed)
        run([sys.executable, '-m', 'pip', '--python', installed / 'bin/python', 'install', '--no-index', '--no-cache-dir', '--find-links', ROOT / '.cache/wheels', next(wheels.glob('*.whl'))], cwd=base)
        env = {**os.environ, 'PYTHONNOUSERSITE': '1'}
        env.pop('PYTHONPATH', None)
        # The installed import must come from the isolated site-packages.
        run([installed / 'bin/python', '-c', 'import calendar_audit; assert "site-packages" in calendar_audit.__file__'], cwd=base, env=env)
        args = [installed / 'bin/calendar-audit', DATA / 'bsd.ics', DATA / 'legal-and-policy.ics', '--start', '2025-02-01', '--end', '2025-02-03']
        for zone, offset in [('America/New_York', -5), ('Europe/Brussels', 1), ('Asia/Tokyo', 9)]:
            output = base / zone.split('/')[-1]
            run(args + ['--timezone', zone, '--floating-timezone', 'Europe/Brussels', '--output', output], cwd=base, env=env)
            report = json.loads((output / 'report.json').read_text())
            oracle(report, intervals, offset)
            if zone == 'America/New_York':
                for name in ('report.html', 'report.json'):
                    assert (output / name).read_bytes() == (DATA / 'report' / name).read_bytes(), f'Stale checked-in {name}'
                browser_check(output / 'report.html')
        output = base / 'unasserted'
        result = subprocess.run([str(x) for x in args + ['--timezone', 'America/New_York', '--output', output]], cwd=base, env=env)
        assert result.returncode == 2
        report = json.loads((output / 'report.json').read_text())
        assert not report['complete'] and len(report['issues']) == 2
        print('Unasserted nonstandard source timezones correctly produce INCOMPLETE / exit 2', flush=True)
    print('Public calendar installed workflow passed', flush=True)


if __name__ == '__main__':
    main()
