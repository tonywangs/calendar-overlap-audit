"""Network-blocked Chromium: explanations, exception links, filters and keyboard."""
import json
import os
from pathlib import Path
import re

import pytest
from playwright.sync_api import expect, sync_playwright

from calendar_audit.availability_cli import main
from test_schedule import SPEC2

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT/'.cache/ms-playwright'))


@pytest.mark.parametrize('incomplete', [False, True])
def test_schedule_offline_navigation(tmp_path, make_ics, incomplete):
    source = make_ics('UID:hostile\nSUMMARY:<img src=https://invalid.test/x onerror=window.pwned=1>\n'
                      'DTSTART:20260306T100000Z\nDTEND:20260306T110000Z',
                      *(['UID:bad\nDTSTART:20260306T090000Z\nRRULE:FREQ=MONTHLY'] if incomplete else []))
    spec = tmp_path/'working.json'
    spec.write_text(json.dumps(SPEC2))
    output = tmp_path/'out'
    assert main([str(source), '--spec', str(spec), '--output', str(output)]) == (2 if incomplete else 0)
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
        page.goto((output/'report.html').as_uri())
        expect(page.get_by_role('heading', name='Working-window settings · specification v2')).to_be_visible()
        expect(page.locator('[data-schedule-day]:visible')).to_have_count(3)
        expect(page.locator('#d2026-03-08')).to_contain_text('Closed')
        expect(page.locator('#d2026-03-07')).to_contain_text('Applied date replacement: 10:00–12:00')
        assert page.locator('img').count() == 0 and page.evaluate('window.pwned') is None
        page.keyboard.press('Tab')
        expect(page.locator(':focus')).to_have_text('Skip to report')
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#main$'))
        page.locator('#availability-date').fill('2026-03-06')
        expect(page.locator('[data-schedule-day]:visible')).to_have_count(1)
        # A visible exception-navigation link reveals a filtered-out explanation.
        page.get_by_role('navigation', name='Date replacements').locator('a[href="#d2026-03-07"]').focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#d2026-03-07$'))
        expect(page.locator('#d2026-03-07')).to_be_visible()
        expect(page.locator('#availability-date')).to_have_value('')
        page.locator('#d2026-03-07 a').focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#w3$'))
        page.locator('#w3 a[href="#d2026-03-07"]').click()
        expect(page).to_have_url(re.compile('#d2026-03-07$'))
        if incomplete:
            expect(page.locator('[data-gap]')).to_have_count(0)
            expect(page.locator('#d2026-03-06')).to_contain_text('Incomplete analysis')
            expect(page.locator('#d2026-03-08')).to_contain_text('Calendar analysis incomplete')
        else:
            expect(page.locator('[data-gap]:visible')).to_have_count(4)
            page.locator('#search').fill('no match')
            expect(page.locator('#o1')).to_be_hidden()
            page.locator('#g1 a[href="#o1"]').focus()
            page.keyboard.press('Enter')
            expect(page.locator('#o1')).to_be_visible()
            expect(page).to_have_url(re.compile('#o1$'))
            page.locator('#o1 a').first.click()
            expect(page).to_have_url(re.compile('#e1$'))
            page.locator('#e1 a[href="#s1"]').click()
            expect(page.locator('#s1')).to_contain_text('SHA-256')
        page.keyboard.press('Escape')
        expect(page.locator(':focus')).to_have_attribute('id', 'availability-date')
        expect(page.locator('#availability-date')).to_have_value('')
        page.locator('#availability-date').fill('2026-03-08')
        expect(page.locator('[data-gap]:visible')).to_have_count(0)
        expect(page.locator('[data-schedule-day]:visible')).to_have_count(1)
        page.get_by_role('button', name='Clear date', exact=True).click()
        expect(page.locator('[data-schedule-day]:visible')).to_have_count(3)
        assert page.evaluate('''() => [...document.querySelectorAll('a')].every(a =>
            a.getAttribute('href').startsWith('#') && document.getElementById(a.getAttribute('href').slice(1)))''')
        assert not errors and not requests
        context.close()
        context = browser.new_context(offline=True, java_script_enabled=False)
        page = context.new_page()
        page.goto((output/'report.html').as_uri())
        expect(page.locator('[data-schedule-day]:visible')).to_have_count(3)
        expect(page.locator('noscript').first).to_be_visible()
        browser.close()
