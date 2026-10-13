import argparse
from pathlib import Path
from uuid import uuid4
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:8766')
parser.add_argument('--token-file', type=Path, default=Path('data/access-token'))
parser.add_argument('--screenshots', type=Path, default=Path('data/ui-check'))
args = parser.parse_args()
assert urlparse(args.base_url).hostname in {"127.0.0.1", "localhost", "::1"}, "Use a local isolated preview server"
args.screenshots.mkdir(parents=True, exist_ok=True)
errors = []
with sync_playwright() as p:
    request = p.request.new_context(base_url=args.base_url, extra_http_headers={'Authorization': 'Bearer ' + args.token_file.read_text().strip()})
    status = request.get('/api/status')
    assert status.ok and not status.json()['delivery_enabled'], 'Browser tests require delivery disabled'
    real_status = status.json()
    request.dispose()
    browser = p.chromium.launch(channel='chrome', headless=True)
    for width in (390, 1440):
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(args.base_url)
        page.get_by_label('Access token', exact=True).fill(args.token_file.read_text().strip())
        page.get_by_role('button', name='Unlock').click()
        expect(page.locator('#console')).to_be_visible()
        page.get_by_role('button', name='Capture inbox', exact=True).click()
        before = page.locator('.receipt-item').count()
        page.get_by_role('button', name='Use synthetic sample').click()
        assert page.locator('.receipt-item').count() == before
        sample = page.locator('#receipt-text').input_value().replace('SYNTHETIC-order-001', 'SYNTHETIC-' + uuid4().hex)
        page.locator('#receipt-text').fill(sample)
        page.get_by_role('button', name='Save for review', exact=True).click()
        expect(page.locator('#receipt-review')).to_be_visible()
        expect(page.locator('#review-account')).to_have_value('SYNTHETIC-demo')
        page.screenshot(path=str(args.screenshots / f'capture-review-{width}.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.get_by_role('button', name='Queue user-confirmed alert', exact=True).click()
        expect(page.locator('#receipt-result')).to_contain_text('confirmed')
        page.get_by_role('button', name='Activity', exact=False).click()
        expect(page.locator('#history')).to_contain_text('User-confirmed')
        count = page.locator('.history-row').count()
        page.get_by_role('button', name='Capture inbox', exact=True).click()
        page.locator('#receipt-text').fill(sample)
        page.get_by_role('button', name='Save for review', exact=True).click()
        expect(page.locator('#receipt-result')).to_contain_text('confirmed')
        expect(page.locator('#receipt-review')).to_be_hidden()
        page.get_by_role('button', name='Activity', exact=False).click()
        expect(page.locator('.history-row')).to_have_count(count)
        page.get_by_role('button', name='Capture inbox', exact=True).click()
        page.locator('#receipt-text').fill('SYNTHETIC incomplete <img src=x onerror=alert(1)> ' + uuid4().hex)
        page.get_by_role('button', name='Save for review', exact=True).click()
        expect(page.locator('#receipt-review')).to_be_visible()
        expect(page.locator('#review-account')).to_have_value('')
        page.get_by_role('button', name='Reject receipt', exact=True).click()
        expect(page.locator('#receipt-result')).to_contain_text('rejected')
        assert page.locator('#receipt-source img').count() == 0
        assert '\ufffd' not in page.locator('#capture').inner_text(), 'Receipt labels must decode as UTF-8'
        page.screenshot(path=str(args.screenshots / f'capture-{width}.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.get_by_role('button', name='Connections', exact=True).click()
        expect(page.locator('#capabilities')).to_contain_text('Robinhood')
        def synthetic_status(route):
            route.fulfill(json={**real_status, 'monitor': {'selected': 'none', 'running': False},
                                'observer': {'state': 'observing', 'updated': time.time(),
                                             'broker': 'tradier', 'environment': 'sandbox'}})
        page.route('**/api/status', synthetic_status)
        page.get_by_role('button', name='Connections', exact=True).click()
        expect(page.locator('#monitor-state')).to_contain_text('Separate watcher')
        expect(page.locator('#monitor-state')).to_contain_text('Recent heartbeat')
        expect(page.locator('#observer-details')).to_contain_text('tradier')
        expect(page.locator('#observer-details')).to_contain_text('sandbox')
        expect(page.locator('#broker-state')).to_have_text('Observing account')
        page.unroute('**/api/status', synthetic_status)
        page.get_by_role('button', name='Alert studio', exact=True).click()
        expect(page.get_by_label('Show event time', exact=True)).to_be_visible()
        page.get_by_role('button', name='Lock console').click()
        expect(page.locator('#receipt-text')).to_have_value('')
        expect(page.locator('#review-account')).to_have_value('')
        expect(page.locator('#receipt-list')).to_be_empty()
        expect(page.locator('#receipt-source')).to_be_empty()
        page.close()
    browser.close()
assert not errors, errors
print('PASS: 390/1440 capture review, explicit confirmation, activity, duplicate, reject, safe text and lock')
