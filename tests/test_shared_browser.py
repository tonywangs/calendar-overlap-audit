"""Network-blocked Chromium checks of filters, inspection and imported-text isolation."""
from datetime import timedelta
from pathlib import Path
import re
import sys

import pytest
from playwright.sync_api import sync_playwright, expect
from calendar_audit.shared_cli import main

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from shared_cases import BASE, ics, manifest, person, write_case


@pytest.mark.parametrize('width',[375,1280])
def test_shared_report_offline(tmp_path,width):
    lo=BASE.replace(hour=23,minute=30)
    hi=lo+timedelta(hours=3)
    hostile='A </script><img src=https://private.invalid/x>'
    people=[person(hostile,['a.ics'],{'MO':[['23:00','02:00']],'TU':[['02:00','03:00']]}),
            person('B',['b.ics'],{'MO':[['23:00','03:00']]})]
    periods=[(lo+timedelta(hours=1),lo+timedelta(hours=1,minutes=30),'BUSY',False)]
    path=write_case(tmp_path,manifest(people,lo,hi,minimum=600),{
        'a.ics':ics(lo,hi,periods,metadata='COMMENT:PRIVATE <img src=https://private.invalid/secret>'),
        'b.ics':ics(lo,hi-timedelta(minutes=15))})
    output=tmp_path/'out'
    assert main(['--manifest',str(path),'--output',str(output)])==0
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(offline=True,service_workers='block',viewport={'width':width,'height':800})
        requests,errors=[],[]
        def block(route):
            requests.append(route.request.url);route.abort()
        context.route('http://**/*',block);context.route('https://**/*',block)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto((output/'report.html').as_uri())
        expect(page.get_by_role('heading',name='Shared meeting windows',exact=True)).to_be_visible()
        expect(page.locator('[data-window]:visible')).to_have_count(2)
        expect(page.locator('header')).to_contain_text('Coverage has gaps')
        assert page.locator('img').count()==0
        assert 'PRIVATE' not in page.locator('body').inner_text()
        assert page.evaluate('window.pwned') is None
        page.keyboard.press('Tab');expect(page.locator(':focus')).to_have_text('Skip to report')
        page.keyboard.press('Enter');expect(page).to_have_url(re.compile('#main$'))
        page.locator('#w1 summary').focus();page.keyboard.press('Enter')
        expect(page.locator('#w1 details')).to_have_attribute('open','')
        expect(page.locator('#w1 details')).to_contain_text(hostile)
        page.locator('#w1 a[href="#p1"]').focus();page.keyboard.press('Enter')
        expect(page).to_have_url(re.compile('#p1$'))
        expect(page.locator('#p1')).to_be_visible()
        page.locator('#p1 summary').focus();page.keyboard.press('Enter')
        expect(page.locator('#p1 details')).to_contain_text('SHA-256')
        page.locator('#date-filter').fill('2026-03-09')
        expect(page.locator('[data-window]:visible')).to_have_count(1)
        page.locator('#date-filter').fill('2026-03-10')
        expect(page.locator('[data-window]:visible')).to_have_count(2)  # first crosses midnight
        page.locator('#length-filter').fill('4000')
        expect(page.locator('[data-window]:visible')).to_have_count(1)
        page.locator('#date-filter').fill('2026-03-11')
        expect(page.locator('[data-window]:visible')).to_have_count(0)
        expect(page.locator('#shown')).to_have_text('0 of 2 candidate windows shown')
        page.keyboard.press('Escape')
        expect(page.locator(':focus')).to_have_attribute('id','date-filter')
        expect(page.locator('[data-window]:visible')).to_have_count(2)
        page.locator('#length-filter').fill('999999');page.get_by_role('button',name='Clear filters').click()
        expect(page.locator('[data-window]:visible')).to_have_count(2)
        page.locator('#date-filter').fill('2026-03-11')
        page.evaluate("location.hash='w1'")
        expect(page.locator('#w1')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.evaluate('''() => [...document.querySelectorAll('a')].every(a=>a.getAttribute('href').startsWith('#')&&document.getElementById(a.hash.slice(1)))''')
        assert not requests and not errors
        context.close()
        context=browser.new_context(offline=True,java_script_enabled=False,viewport={'width':width,'height':800})
        page=context.new_page();page.goto((output/'report.html').as_uri())
        expect(page.locator('noscript')).to_be_visible()
        expect(page.locator('[data-window]:visible')).to_have_count(2)
        page.locator('#w1 summary').click()
        expect(page.locator('#w1 details')).to_contain_text(hostile)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        browser.close()
