"""Compatibility: a Webull host supplies intents, never destination credentials.

No Webull or Alpaca network calls; exercise the real Windows execution adapter
through a synthetic Alpaca HTTP transport. Source environment is deliberately
not the receiver's environment.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from crier.intent_broker import AlpacaIntentBroker
from crier.intent_engine import IntentEngine
from crier.intent_protocol import IntentEvent


def instruction(symbol, asset, *, action='enter', sequence=1, trade_id=None):
    now = datetime.now(timezone.utc)
    return dict(version=1, event_id=str(uuid4()), trade_id=trade_id or str(uuid4()),
                sequence=sequence, action=action, environment='paper', symbol=symbol,
                asset=asset, quantity=2, limit_price='0.90', created_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=30)).isoformat())


@pytest.mark.parametrize(('symbol', 'asset'), [
    ('SPY261218C00750000', 'option'), ('SPY', 'stock'),
])
def test_source_instruction_reaches_alpaca_paper_without_webull_credentials(tmp_path, symbol, asset):
    import json
    orders = {}
    posted = []
    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.host == 'paper-api.alpaca.markets'
        assert 'webull' not in str(request.headers).lower()
        path = request.url.path
        if path == '/v2/account':
            return httpx.Response(200, json=dict(id='receiver-paper', status='ACTIVE',
                trading_blocked=False, account_blocked=False, currency='USD'))
        if path.startswith('/v2/options/contracts/'):
            return httpx.Response(200, json=dict(symbol=symbol, tradable=True, status='active', size='100'))
        if path.startswith('/v2/assets/'):
            return httpx.Response(200, json={'symbol': symbol, 'tradable': True, 'status': 'active', 'class': 'us_equity'})
        if path == '/v2/orders:by_client_order_id':
            row = orders.get(request.url.params['client_order_id'])
            return httpx.Response(200, json=row) if row else httpx.Response(404)
        if path == '/v2/orders' and request.method == 'POST':
            body = json.loads(request.content)
            posted.append(body)
            row = dict(body, id=str(uuid4()), status='filled', filled_qty=body['qty'], filled_avg_price=body['limit_price'])
            orders[body['client_order_id']] = row
            return httpx.Response(200, json=row)
        if path.startswith('/v2/positions/'):
            return httpx.Response(200, json=dict(symbol=symbol, qty_available='2'))
        raise AssertionError((request.method, str(request.url)))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        broker = AlpacaIntentBroker('paper', 'receiver-key', 'receiver-secret', 'receiver-paper', client)
        engine = IntentEngine(tmp_path / 'receiver.sqlite3', broker)
        engine.save_settings({'enabled': True})
        event = instruction(symbol, asset)
        IntentEvent(**event)
        engine.accept(event)
        engine.tick()
        engine.accept(event)  # A stream reconnect/replay cannot create a second buy.
        engine.tick()
        assert len(posted) == 1
        assert posted[0]['symbol'] == symbol
        assert posted[0]['qty'] == '2'
        assert Decimal(posted[0]['limit_price']) == Decimal('0.90')
        assert posted[0]['side'] == 'buy'
        assert posted[0]['position_intent'] == 'buy_to_open'
        # Host exit must close the same canonical instrument, never a guessed contract.
        engine.accept(instruction(symbol, asset, action='exit', sequence=2, trade_id=event['trade_id']))
        engine.tick()
        assert len(posted) == 2
        assert posted[1]['symbol'] == symbol
        assert posted[1]['qty'] == '2'
        assert posted[1]['position_intent'] == 'sell_to_close'
        restarted = IntentEngine(engine.path, broker)
        restarted.tick()
        assert len(posted) == 2
        assert requests


def test_source_production_is_not_a_valid_replacement_for_destination_environment():
    # Host source environment belongs in its own journal, not intent-v1.
    event = instruction('SPY261218C00750000', 'option')
    event['environment'] = 'production'
    with pytest.raises(ValueError):
        IntentEvent(**event)
    event['environment'] = 'paper'
    event['webull_access_token'] = 'must-never-be-relayed'
    with pytest.raises(ValueError):
        IntentEvent(**event)
