"""Broker activity -> durable alert -> Discord acknowledgement, with mocked HTTPS."""
import json

import httpx

from crier.alpaca import poll_once
from crier.delivery import deliver_once
from crier.store import Store


def test_fill_reaches_discord_once_with_exact_quantity_and_price(tmp_path):
    store = Store(tmp_path / 'flow.sqlite3')
    rows = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=rows))) as broker:
        poll_once(store, broker, 'private-account')
        rows.append({'id': 'execution-1', 'activity_type': 'FILL', 'type': 'fill',
                     'order_id': 'private-order', 'symbol': 'SPY261120C00600000',
                     'side': 'buy', 'qty': '2', 'cum_qty': '2', 'leaves_qty': '0',
                     'price': '1.23', 'transaction_time': '2026-10-19T14:00:00Z'})
        poll_once(store, broker, 'private-account')
        # Restart before delivery, then replay the same broker observation.
        store = Store(tmp_path / 'flow.sqlite3')
        poll_once(store, broker, 'private-account')
    sent = []
    def discord(request):
        payload = json.loads(request.content)
        sent.append(payload)
        assert request.url.params['wait'] == 'true'
        assert payload['allowed_mentions'] == {'parse': []}
        assert 'private-account' not in request.content.decode()
        assert 'private-order' not in request.content.decode()
        return httpx.Response(200, json={'id': '123456789'})
    with httpx.Client(transport=httpx.MockTransport(discord)) as client:
        assert deliver_once(store, 'https://discord.com/api/webhooks/123/test-token', client)
        assert not deliver_once(store, 'https://discord.com/api/webhooks/123/test-token', client)
    assert len(sent) == 1
    fill = store.history()[0]['fill']
    assert (fill['quantity'], fill['price'], fill['environment']) == ('2', '1.23', 'sandbox')
    assert '1.23' in json.dumps(sent[0])
