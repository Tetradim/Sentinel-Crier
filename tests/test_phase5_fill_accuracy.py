"""Offline acceptance of Alpaca execution accounting through Discord delivery.

Only HTTPS boundaries are faked. No live/paper account or UI comparison is
claimed: the real monitor, decimal normalization, journal, renderer and sender
process synthetic standard-option executions.
"""
from decimal import Decimal
import json

import httpx
import pytest

from crier.alpaca import poll_once
from crier.delivery import deliver_once
from crier.models import Settings
from crier.store import Store


SYMBOL = 'SPY261120C00600000'
ACCOUNT = 'private-phase5-account'
KEY = 'synthetic-phase5-api-key'
SECRET = 'synthetic-phase5-api-secret'
WEBHOOK = 'https://discord.com/api/webhooks/123/phase5-test-token'


def activity(identity, side, quantity, cumulative, price, minute):
    return {
        'id': identity, 'activity_type': 'FILL',
        'type': 'fill' if cumulative == 4 else 'partial_fill',
        'order_id': 'private-' + side + '-order', 'symbol': SYMBOL,
        'side': side, 'qty': str(quantity), 'cum_qty': str(cumulative),
        'leaves_qty': str(4 - cumulative), 'price': price,
        'transaction_time': f'2026-10-23T14:{minute:02}:00Z',
    }


EXECUTIONS = [
    activity('buy-first', 'buy', 2, 2, '0.20', 0),
    activity('buy-final', 'buy', 2, 4, '0.22', 1),
    activity('sell-first', 'sell', 1, 1, '0.24', 2),
    activity('sell-final', 'sell', 3, 4, '0.22', 3),
]


class FillRig:
    def __init__(self, folder):
        self.path = folder / 'fills.sqlite3'
        self.store = Store(self.path)
        self.store.save_settings(Settings(format='card', timezone='UTC'))
        self.rows, self.sent, self.broker_requests = [], [], []
        self.broker = httpx.Client(
            transport=httpx.MockTransport(self.broker_response), trust_env=False,
            headers={'APCA-API-KEY-ID': KEY, 'APCA-API-SECRET-KEY': SECRET})
        self.discord = httpx.Client(
            transport=httpx.MockTransport(self.discord_response), trust_env=False)
        assert self.poll() == {
            'state': 'observing', 'activities': 0, 'fills': 0, 'enrolled': True}

    def broker_response(self, request):
        assert request.method == 'GET'
        assert request.url.host == 'paper-api.alpaca.markets'
        assert request.url.path == '/v2/account/activities/FILL'
        assert request.headers['APCA-API-KEY-ID'] == KEY
        assert request.headers['APCA-API-SECRET-KEY'] == SECRET
        self.broker_requests.append(request)
        # Deliberately replay the complete page even when a cursor is supplied:
        # repeated broker observations must be deduplicated durably.
        return httpx.Response(200, json=self.rows)

    def discord_response(self, request):
        assert request.method == 'POST'
        assert request.url.host == 'discord.com'
        assert request.url.params['wait'] == 'true'
        payload = json.loads(request.content)
        assert payload['allowed_mentions'] == {'parse': []}
        public_request = str(request.headers) + request.content.decode()
        for private in (ACCOUNT, KEY, SECRET, 'private-buy-order', 'private-sell-order'):
            assert private not in public_request
        self.sent.append(payload)
        return httpx.Response(200, json={'id': str(9000 + len(self.sent))})

    def poll(self):
        return poll_once(self.store, self.broker, ACCOUNT, 'paper')

    def add(self, row):
        self.rows.append(row)
        assert self.poll()['fills'] == 1

    def restart(self):
        self.store = Store(self.path)
        self.store.recover()

    def deliver(self, client=None):
        return deliver_once(self.store, WEBHOOK, client or self.discord)

    def close(self):
        self.broker.close()
        self.discord.close()


@pytest.fixture
def rig(tmp_path):
    result = FillRig(tmp_path)
    yield result
    result.close()


def test_phase5_option_buy_sell_accounting_replay_and_restart(rig):
    expected = [
        ('BUY', '2', '2', '0.2', '0.20', 'Partial order fill'),
        ('BUY', '2', '4', '0.22', '0.22', 'Order filled'),
        ('SELL', '1', '1', '0.24', '0.24', 'Partial order fill'),
        ('SELL', '3', '4', '0.22', '0.22', 'Order filled'),
    ]
    for index, (execution, values) in enumerate(zip(EXECUTIONS, expected)):
        rig.add(execution)
        rig.restart()  # Reopen the actual SQLite journal before every send.
        assert rig.poll()['fills'] == 0
        assert rig.deliver()
        assert not rig.deliver()
        job = next(row for row in rig.store.history()
                   if row['fill']['occurred_at'] == execution['transaction_time'])
        fill, card = job['fill'], rig.sent[index]['embeds'][0]
        side, delta, cumulative, price, displayed_price, status = values
        assert (fill['side'], fill['quantity'], fill['cumulative_qty'], fill['price']) == (
            side, delta, cumulative, price)
        assert fill['symbol'] == SYMBOL
        assert (fill['contract'], fill['expiration']) == ('SPY $600C', '2026-11-20')
        assert fill['verification'] == 'broker_reported'
        assert fill['time_basis'] == 'execution'
        assert (fill['broker'], fill['environment']) == ('alpaca', 'sandbox')
        assert card['title'] == 'SPY $600C · 2026-11-20'
        assert card['description'] == (
            f"{'Bought' if side == 'BUY' else 'Sold'} · Filled {delta}× @ ${displayed_price}")
        fields = {field['name']: field['value'] for field in card['fields']}
        assert fields['Order filled so far'] == cumulative + ' contracts'
        assert fields['Status'] == status
        assert fields['Executed'] == f'Oct 23, 2026 · 02:0{index}:00 PM UTC'
        assert card['footer']['text'] == 'Alpaca · sandbox · Broker-reported · ' + job['id']
        assert job['payload'] == rig.sent[index]
        assert (job['status'], job['attempts'], job['message_id']) == ('sent', 1, str(9001 + index))

    fills = [row['fill'] for row in rig.store.history()]
    for side, premium in [('BUY', Decimal('84')), ('SELL', Decimal('90'))]:
        trades = [fill for fill in fills if fill['side'] == side]
        assert sum(Decimal(fill['quantity']) for fill in trades) == 4
        # Standard OCC option multiplier: four contracts, not four shares.
        assert sum(Decimal(fill['quantity']) * Decimal(fill['price']) * 100
                   for fill in trades) == premium
    with rig.store.connect() as db:
        totals = {row['id']: json.loads(row['data'])
                  for row in db.execute('SELECT id,data FROM alpaca_totals')}
        averages = sorted((row['qty'], Decimal(row['price']))
                          for row in db.execute('SELECT qty,price FROM orders'))
        assert db.execute('SELECT count(*) FROM alpaca_activities').fetchone()[0] == 4
    assert totals['private-buy-order']['cost'] == '0.84'
    assert totals['private-sell-order']['cost'] == '0.90'
    assert averages == [('4', Decimal('0.21')), ('4', Decimal('0.225'))]
    rig.restart()
    assert rig.poll()['fills'] == 0
    assert rig.broker_requests[-1].url.params['page_token'] == 'sell-final'
    assert not rig.deliver()
    assert len(rig.sent) == len(rig.store.history()) == 4


@pytest.mark.parametrize('failure', ['connect', 'rate_limit'])
def test_phase5_transient_discord_failure_recovers_frozen_fill(rig, monkeypatch, failure):
    clock = [1000.0]
    monkeypatch.setattr('crier.store.time.time', lambda: clock[0])
    rig.add(EXECUTIONS[0])
    frozen = rig.store.history()[0]
    attempts = []

    def unavailable(request):
        attempts.append(json.loads(request.content))
        if failure == 'connect':
            raise httpx.ConnectError('Synthetic connection failure', request=request)
        return httpx.Response(429, json={'retry_after': 30})

    with httpx.Client(transport=httpx.MockTransport(unavailable), trust_env=False) as client:
        assert rig.deliver(client)
        assert not rig.deliver(client)
        rig.restart()
        assert rig.poll()['fills'] == 0
        pending = rig.store.history()[0]
        assert (pending['status'], pending['attempts'], pending['due']) == ('pending', 1, 1030)
        assert pending['fill'] == frozen['fill']
        assert pending['payload'] == frozen['payload']
        assert pending['message_id'] is None
        clock[0] = 1029
        assert not rig.deliver(client)
    clock[0] = 1030
    assert rig.deliver()
    assert attempts == rig.sent == [frozen['payload']]
    saved = rig.store.history()[0]
    assert (saved['status'], saved['attempts'], saved['message_id']) == ('sent', 2, '9001')
    rig.restart()
    assert rig.poll()['fills'] == 0
    assert not rig.deliver()
    assert len(rig.store.history()) == 1


@pytest.mark.parametrize('failure', ['lost_response', 'server_error', 'process_restart'])
def test_phase5_uncertain_discord_send_never_silently_reposts(rig, monkeypatch, failure):
    clock = [2000.0]
    monkeypatch.setattr('crier.store.time.time', lambda: clock[0])
    rig.add(EXECUTIONS[0])
    frozen = rig.store.history()[0]
    possibly_delivered = []

    def ambiguous(request):
        possibly_delivered.append(json.loads(request.content))
        if failure == 'lost_response':
            raise httpx.ReadTimeout('Synthetic lost acknowledgement', request=request)
        if failure == 'process_restart':
            # Process dies after sending but before persisting acknowledgement.
            raise SystemExit('Synthetic sender process termination')
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(ambiguous), trust_env=False) as client:
        if failure == 'process_restart':
            with pytest.raises(SystemExit):
                rig.deliver(client)
            assert rig.store.history()[0]['status'] == 'sending'
        else:
            assert rig.deliver(client)
    assert possibly_delivered == [frozen['payload']]
    rig.restart()
    assert rig.poll()['fills'] == 0
    clock[0] += 86400
    assert not rig.deliver()
    saved = rig.store.history()[0]
    assert (saved['status'], saved['attempts'], saved['message_id']) == ('uncertain', 1, None)
    assert saved['fill'] == frozen['fill']
    assert saved['payload'] == frozen['payload']
    assert saved['note']
    assert rig.sent == []
    assert len(rig.store.history()) == 1
