import json
import os
from pathlib import Path
import re

import pytest

from playwright.sync_api import expect, sync_playwright

from calendar_audit.availability_cli import main
from test_availability import SPEC

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.cache/ms-playwright'))


@pytest.mark.parametrize('dense', [False, True])
def test_availability_offline_browser_filter_citations_keyboard_and_hostile_text(tmp_path, make_ics, dense):
    source = make_ics('UID:hostile\nSUMMARY:<img src=https://invalid.test/x onerror=window.pwned=1>\nDTSTART:20260306T100000Z\nDTEND:20260306T110000Z',
                      'UID:second\nSUMMARY:Second day\nDTSTART:20260307T100000Z\nDTEND:20260307T110000Z',
                      *[f'UID:dense-{i}\nDTSTART:20260306T100000Z\nDTEND:20260306T110000Z' for i in range(250 if dense else 0)])
    spec = tmp_path / 'working.json'
    spec.write_text(json.dumps({**SPEC, 'end':'2026-03-08'}))
    out = tmp_path / 'out'
    assert main([str(source),'--spec',str(spec),'--output',str(out)]) == 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(offline=True, service_workers='block')
        requests, errors = [], []
        def block(route):
            requests.append(route.request.url)
            route.abort()
        context.route('http://**/*',block)
        context.route('https://**/*',block)
        page = context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto((out / 'report.html').as_uri())
        assert page.title() == 'Calendar availability audit'
        assert 'Overlap pairs were not computed' in page.locator('body').inner_text()
        assert '0 overlap pairs' not in page.locator('body').inner_text()
        expect(page.locator('[data-gap]:visible')).to_have_count(4)
        assert page.locator('img').count() == 0 and page.evaluate('window.pwned') is None
        page.keyboard.press('Tab')
        expect(page.locator(':focus')).to_have_text('Skip to report')
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#main$'))
        page.locator('#availability-date').fill('2026-03-06')
        expect(page.locator('[data-gap]:visible')).to_have_count(2)
        expect(page.locator('[data-availability-date]:visible')).to_have_count(3)
        assert '2 candidate intervals shown' in page.locator('#availability-status').inner_text()
        # Underlying occurrence filters can hide a boundary citation target.
        page.locator('#search').fill('Second day')
        expect(page.locator('#o1')).to_be_hidden()
        page.locator('#g1 a[href="#o1"]').focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#o1$'))
        expect(page.locator('#o1')).to_be_visible()
        page.locator('#o1 a').focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#e1$'))
        page.locator('#e1 a[href="#s1"]').focus()
        page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#s1$'))
        assert 'SHA-256' in page.locator('#s1').inner_text()
        page.keyboard.press('Escape')
        expect(page.locator('#availability-date')).to_have_value('')
        expect(page.locator(':focus')).to_have_attribute('id','availability-date')
        expect(page.locator('[data-gap]:visible')).to_have_count(4)
        # Chromium exposes individual date segments in the native Tab order.
        for _ in range(5):
            page.keyboard.press('Tab')
            if page.evaluate('document.activeElement.id') == 'clear-date':
                break
        expect(page.locator(':focus')).to_have_attribute('id','clear-date')
        page.locator('#availability-date').fill('2026-03-10')
        expect(page.locator('[data-gap]:visible')).to_have_count(0)
        page.get_by_role('button',name='Clear date',exact=True).click()
        expect(page.locator('[data-gap]:visible')).to_have_count(4)
        assert page.evaluate('''() => [...document.querySelectorAll('a')].every(a =>
            a.getAttribute('href').startsWith('#') && document.getElementById(a.getAttribute('href').slice(1)))''')
        assert not errors and not requests
        context.close()
        context = browser.new_context(offline=True,java_script_enabled=False)
        page = context.new_page()
        page.goto((out / 'report.html').as_uri())
        expect(page.locator('[data-gap]:visible')).to_have_count(4)
        assert page.locator('noscript').first.is_visible()
        browser.close()


def test_incomplete_browser_has_no_candidate_cards(tmp_path, make_ics):
    source = make_ics('UID:bad\nDTSTART:20260306T090000Z\nRRULE:FREQ=MONTHLY')
    spec = tmp_path / 'working.json'
    spec.write_text(json.dumps(SPEC))
    out = tmp_path / 'out'
    assert main([str(source),'--spec',str(spec),'--output',str(out)]) == 2
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(offline=True)
        page.goto((out / 'report.html').as_uri())
        expect(page.get_by_text('INCOMPLETE: candidate intervals withheld.',exact=True)).to_be_visible()
        expect(page.locator('[data-gap]')).to_have_count(0)
        browser.close()
