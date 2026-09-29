"""Real Chromium checks; intentionally fail rather than skip missing browsers."""
import os
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from calendar_audit.cli import main
from conftest import FIXTURES


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.cache/ms-playwright'))


def test_network_blocked_browser_core_use_case(tmp_path):
    out = tmp_path / 'report'
    assert main([str(FIXTURES / 'synthetic.ics'), '--start', '2026-03-06', '--end', '2026-03-11',
                 '--timezone', 'America/New_York', '--output', str(out)]) == 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(offline=True, service_workers='block')
        requests, errors = [], []
        def block(route):
            requests.append(route.request.url)
            route.abort()
        context.route('http://**/*', block)
        context.route('https://**/*', block)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto((out / 'report.html').as_uri())
        assert page.title() == 'Calendar overlap audit'
        assert page.locator('[data-occurrence]:visible').count() == 11
        assert page.locator('[data-pair]:visible').count() == 3
        assert page.locator('img').count() == 0
        assert page.evaluate('window.pwned') is None
        assert page.locator('h3').filter(has_text='Synthetic <img').count() == 2
        # Native keyboard skip link, filtering and Escape reset.
        page.keyboard.press('Tab')
        assert page.locator(':focus').inner_text() == 'Skip to report'
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile(r'#main$'))
        page.locator('#search').focus()
        page.keyboard.type('nested')
        assert page.locator('[data-occurrence]:visible').count() == 1
        assert page.locator('[data-pair]:visible').count() == 2
        assert 'Totals remain unfiltered' in page.locator('#filter-status').inner_text()
        # Pair -> occurrence -> event -> occurrence backreference, all with Enter.
        pair_link = page.locator('[data-pair]:visible a[href="#o6"]').first
        pair_link.focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile(r'#o6$'))
        record_link = page.locator('#o6 a')
        record_link.focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile(r'#e3$'))
        back = page.locator('#e3 a[href="#o6"]')
        back.focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile(r'#o6$'))
        page.keyboard.press('Escape')
        assert page.locator('#search').input_value() == ''
        assert page.locator(':focus').get_attribute('id') == 'search'
        assert page.locator('[data-occurrence]:visible').count() == 11
        page.keyboard.press('Tab')
        assert page.locator(':focus').get_attribute('id') == 'kind'
        page.keyboard.press('ArrowDown')
        page.keyboard.press('ArrowDown')
        page.keyboard.press('Enter')
        assert page.locator('#kind').input_value() == 'all-day'
        assert page.locator('[data-occurrence]:visible').count() == 1
        assert page.locator('[data-pair]:visible').count() == 0
        # A backreference to a filtered-out occurrence resets filters first.
        page.locator('#e3 a[href="#o6"]').click()
        assert page.locator('#o6').is_visible()
        page.locator('#search').fill('no matches anywhere')
        assert page.locator('[data-occurrence]:visible').count() == 0
        page.get_by_role('button', name='Clear filters').click()
        page.locator('#source').select_option('s1')
        assert page.locator('[data-occurrence]:visible').count() == 11
        assert page.locator('table tbody tr').count() == 5
        # Every static citation resolves; no imported URLs became anchors.
        assert page.evaluate('''() => [...document.querySelectorAll('a')].every(a =>
            a.getAttribute('href').startsWith('#') && document.getElementById(a.getAttribute('href').slice(1)))''')
        assert not requests and not errors
        context.close()
        # Progressive enhancement: report remains usable with JavaScript off.
        context = browser.new_context(java_script_enabled=False, offline=True)
        page = context.new_page()
        page.goto((out / 'report.html').as_uri())
        assert page.locator('[data-occurrence]:visible').count() == 11
        assert page.locator('noscript').is_visible()
        browser.close()


def test_source_filters_and_incomplete_warning(tmp_path, make_ics):
    first = make_ics('UID:a\nSUMMARY:First source\nDTSTART:20260306T090000Z\nDTEND:20260306T110000Z', name='first.ics')
    second = make_ics('UID:b\nSUMMARY:Second source\nDTSTART:20260306T100000Z\nDTEND:20260306T120000Z',
                      'UID:c\nDTSTART;TZID=Unknown/Zone:20260306T150000', name='second.ics')
    out = tmp_path / 'out'
    assert main([str(first), str(second), '--start', '2026-03-06', '--end', '2026-03-07',
                 '--timezone', 'UTC', '--output', str(out)]) == 2
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(offline=True, service_workers='block')
        page = context.new_page()
        page.goto((out / 'report.html').as_uri())
        expect(page.get_by_text('INCOMPLETE ANALYSIS.', exact=True)).to_be_visible()
        page.locator('#source').select_option('s2')
        expect(page.locator('[data-occurrence]:visible')).to_have_count(1)
        expect(page.locator('[data-occurrence]:visible h3')).to_have_text('Second source')
        expect(page.locator('[data-pair]:visible')).to_have_count(1)
        # Following a citation to the other source reveals its hidden occurrence.
        page.locator('[data-pair] a[href="#o1"]').click()
        expect(page.locator('#o1')).to_be_visible()
        expect(page.locator('#source')).to_have_value('')
        browser.close()


def test_override_citations_filters_cancellations_and_hostile_text(tmp_path):
    source = tmp_path / 'override.ics'
    source.write_text((FIXTURES / 'overrides.ics').read_text().replace(
        'Moved from after window', 'Moved <img src=https://invalid.test/x onerror=window.pwned=1> & </script>'))
    out = tmp_path / 'out'
    assert main([str(source), '--start','2026-03-03','--end','2026-03-06',
                 '--timezone','UTC','--output',str(out)]) == 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(offline=True, service_workers='block')
        requests, errors = [], []
        def block(route):
            requests.append(route.request.url)
            route.abort()
        context.route('http://**/*', block)
        context.route('https://**/*', block)
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto((out/'report.html').as_uri())
        expect(page.locator('[data-occurrence]')).to_have_count(3)
        expect(page.locator('[data-pair]')).to_have_count(3)
        assert '2026-03-04T10:00:00Z' in page.locator('#cancellations + ul').inner_text()
        assert page.locator('img').count() == 0 and page.evaluate('window.pwned') is None
        # Filter hides a replacement; keyboard-follow a master backreference.
        page.locator('#search').fill('Another')
        expect(page.locator('[data-occurrence]:visible')).to_have_count(1)
        page.locator('#e1 a[href="#o2"]').focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#o2$'))
        expect(page.locator('#o2')).to_be_visible()
        page.locator('#o2 a[href="#e3"]').first.focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#e3$'))
        page.locator('#e3 a[href="#e1"]').focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#e1$'))
        page.locator('#e1 a[href="#e5"]').focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#e5$'))
        assert 'cancelled' in page.locator('#e5').inner_text()
        page.locator('#source').select_option('s1')
        expect(page.locator('[data-occurrence]:visible')).to_have_count(3)
        page.locator('#kind').select_option('all-day')
        expect(page.locator('[data-occurrence]:visible')).to_have_count(0)
        page.keyboard.press('Escape')
        expect(page.locator('[data-occurrence]:visible')).to_have_count(3)
        assert page.evaluate('''() => [...document.querySelectorAll('a')].every(a =>
            a.getAttribute('href').startsWith('#') && document.getElementById(a.getAttribute('href').slice(1)))''')
        assert not errors and not requests
        browser.close()
