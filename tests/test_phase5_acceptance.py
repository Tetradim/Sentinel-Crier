"""Offline acceptance: durable PC devices -> authorized relay -> Alpaca HTTP adapter.

All broker responses and credentials are synthetic. These tests do not establish
live/paper account, hosted relay, native mobile, or physical-device acceptance.
"""
import asyncio
from decimal import Decimal
import json

from fastapi import FastAPI, Header, HTTPException
import httpx
import pytest

from crier.intent_broker import AlpacaIntentBroker
from crier.intent_device import IntentDevice
from crier.intent_relay import IntentRelay, sync_router


SYMBOL = 'SPY261212C00750000'
ADMIN = 'synthetic-acceptance-administrator-token'
ASYNC_CLIENT = httpx.AsyncClient


class AlpacaScript:
    """Stateful HTTP boundary; execution logic stays in the real adapter/engine."""

    def __init__(self, account):
        self.account = account
        self.orders = {}
        self.posts = []
        self.cancels = []
        self.lose_next_response = False
        self.fill_during_cancel = None
        self.lookup_hidden = False
        self.client = httpx.Client(transport=httpx.MockTransport(self.respond),
                                  trust_env=False)
        self.broker = AlpacaIntentBroker('paper', 'synthetic-key',
                                        'synthetic-secret', account, self.client)

    def respond(self, request):
        assert request.url.host == 'paper-api.alpaca.markets'
        path = request.url.path
        if request.method == 'GET' and path == '/v2/account':
            return httpx.Response(200, json={'id': self.account, 'status': 'ACTIVE',
                                          'trading_blocked': False, 'account_blocked': False})
        if request.method == 'GET' and path == '/v2/options/contracts/' + SYMBOL:
            return httpx.Response(200, json={'symbol': SYMBOL, 'tradable': True,
                                          'status': 'active', 'size': '100'})
        if request.method == 'POST' and path == '/v2/orders':
            body = json.loads(request.content)
            self.posts.append(body)
            cid = body['client_order_id']
            assert cid not in self.orders, 'Duplicate broker POST after durable reservation'
            row = dict(body, id=f'{self.account}-{len(self.posts)}', status='new',
                       filled_qty='0', filled_avg_price=None)
            self.orders[cid] = row
            if self.lose_next_response:
                self.lose_next_response = False
                raise httpx.ReadTimeout('Synthetic lost POST response', request=request)
            return httpx.Response(200, json=row)
        if request.method == 'GET' and path == '/v2/orders:by_client_order_id':
            row = self.orders.get(request.url.params['client_order_id'])
            return httpx.Response(200, json=row) if row and not self.lookup_hidden else httpx.Response(404)
        if request.method == 'DELETE' and path.startswith('/v2/orders/'):
            row = next(row for row in self.orders.values() if row['id'] == path.rsplit('/', 1)[1])
            self.cancels.append(row['id'])
            if self.fill_during_cancel is not None:
                self.fill(row['client_order_id'], self.fill_during_cancel, 'filled')
                self.fill_during_cancel = None
                return httpx.Response(422, json={'message': 'already filled'})
            row['status'] = 'canceled'
            return httpx.Response(204)
        if request.method == 'GET' and path == '/v2/positions/' + SYMBOL:
            held = sum((Decimal(row['filled_qty']) * (1 if row['side'] == 'buy' else -1)
                        for row in self.orders.values()), Decimal(0))
            return httpx.Response(200, json={'symbol': SYMBOL, 'qty_available': str(held)})
        raise AssertionError(f'Unexpected broker HTTP: {request.method} {request.url}')

    def fill(self, cid, quantity, status='partially_filled'):
        self.orders[cid].update(filled_qty=str(quantity), status=status,
                                filled_avg_price='0.20')


class OneResponse(httpx.AsyncBaseTransport):
    """Run real device loops for one HTTP exchange, without background polling."""

    def __init__(self, app, stop):
        self.transport = httpx.ASGITransport(app=app)
        self.stop = stop
        self.responses = []

    async def handle_async_request(self, request):
        # Empty polling must also finish immediately if a test regresses delivery.
        if request.method == 'GET':
            request.url = request.url.copy_set_param('wait', '0')
        response = await self.transport.handle_async_request(request)
        await response.aread()
        self.responses.append(response)
        self.stop.set()
        return response


class AcceptanceRig:
    def __init__(self, folder, monkeypatch):
        self.folder, self.monkeypatch = folder, monkeypatch
        self.runner = asyncio.Runner()
        self.relay = IntentRelay(folder / 'relay.sqlite3')
        self.app = FastAPI()

        def admin(authorization: str = Header(default='')):
            if authorization != 'Bearer ' + ADMIN:
                raise HTTPException(401)

        self.app.include_router(sync_router(self.relay, admin))
        response = self.request('POST', '/api/sync/channels', ADMIN,
                                json={'name': 'Offline acceptance', 'environment': 'paper'})
        assert response.status_code == 200
        self.pair = response.json()
        self.host_api, self.follower_api = AlpacaScript('synthetic-host'), AlpacaScript('synthetic-follower')
        self.host = self.device('host', self.host_api)
        self.follower = self.device('follower', self.follower_api)
        self.follower.engine.save_settings({'enabled': True})

    def request(self, method, path, token, **kwargs):
        async def run():
            async with ASYNC_CLIENT(transport=httpx.ASGITransport(app=self.app),
                                    base_url='http://localhost', trust_env=False) as client:
                return await client.request(method, path, headers={'Authorization': 'Bearer ' + token}, **kwargs)
        return self.runner.run(run())

    def device(self, role, api):
        device = IntentDevice(self.folder / role, api.broker)
        device.configure({'url': 'http://localhost', 'token': self.pair[role + '_token'],
                          'environment': 'paper', 'role': role})
        return device

    def pump(self, device, method):
        async def run():
            stop = asyncio.Event()
            transport = OneResponse(self.app, stop)
            with self.monkeypatch.context() as patch:
                patch.setattr(httpx, 'AsyncClient', lambda **kw: ASYNC_CLIENT(transport=transport, **kw))
                await asyncio.wait_for(getattr(device, method)(stop), timeout=3)
            assert len(transport.responses) == 1
            assert transport.responses[0].status_code == 200
        self.runner.run(run())

    def deliver(self):
        self.pump(self.host, 'publish_loop')
        assert not self.host.outgoing()
        self.pump(self.follower, 'receive_loop')

    def command(self, action='enter', **values):
        if action == 'enter':
            values = dict(symbol=SYMBOL, asset='option', quantity=4, limit_price='0.20') | values
        result = self.host.command(action, **values)
        self.deliver()
        return result

    def restart_follower(self):
        self.follower = IntentDevice(self.folder / 'follower', self.follower_api.broker)
        assert self.follower.engine.load_settings()['enabled']


@pytest.fixture
def rig(tmp_path, monkeypatch):
    result = AcceptanceRig(tmp_path, monkeypatch)
    yield result
    result.host_api.client.close()
    result.follower_api.client.close()
    result.runner.close()


def test_phase5_exact_option_before_host_fill_and_duplicate_delivery(rig):
    event = rig.command()
    # Receiver execution is driven by intent, while host has no broker order/fill.
    assert rig.host_api.posts == []
    assert rig.follower.engine.tick()[0]['state'] == 'submitted'
    assert rig.follower_api.posts == [{
        'symbol': SYMBOL, 'qty': '4', 'side': 'buy', 'type': 'limit',
        'client_order_id': 'si-' + event.event_id + '-b', 'limit_price': '0.20',
        'time_in_force': 'day', 'position_intent': 'buy_to_open'}]
    assert Decimal(rig.follower_api.posts[0]['limit_price']) == Decimal('0.20')
    assert rig.request('POST', '/api/sync/events', rig.pair['follower_token'], json=event.to_dict()).status_code == 401
    assert rig.request('GET', '/api/sync/events?wait=0', rig.pair['host_token']).status_code == 401
    assert rig.request('POST', '/api/sync/events', rig.pair['host_token'], json=event.to_dict()).status_code == 200
    # Replay the persisted stream after restart, as if the cursor acknowledgement was lost.
    rig.restart_follower()
    with rig.follower.db() as db:
        db.execute('DELETE FROM cursors')
    rig.pump(rig.follower, 'receive_loop')
    assert rig.follower.engine.tick()[0]['state'] == 'working'
    assert len(rig.follower_api.posts) == 1
    with rig.follower.engine._db() as db:
        assert db.execute('SELECT count(*) FROM intent_events').fetchone()[0] == 1
    with rig.follower.db() as db:
        assert db.execute('SELECT cursor FROM cursors').fetchone()[0] > 0


def test_phase5_replace_partial_fill_subtracts_cumulative_quantity(rig):
    event = rig.command()
    rig.follower.engine.tick()
    cid = rig.follower_api.posts[0]['client_order_id']
    rig.follower_api.fill(cid, 2)
    replacement = rig.command('replace', trade_id=event.trade_id, quantity=5, limit_price='0.23')
    assert rig.follower.engine.tick()[0]['state'] == 'cancel_pending'
    assert len(rig.follower_api.posts) == 1
    rig.restart_follower()
    assert rig.follower.engine.tick()[0]['state'] == 'submitted'
    assert [(row['qty'], row['limit_price']) for row in rig.follower_api.posts] == [('4', '0.20'), ('3', '0.23')]
    assert rig.follower_api.posts[1]['client_order_id'] == 'si-' + replacement.event_id + '-b'
    assert len(rig.follower_api.cancels) == 1
    assert rig.follower.engine.status()['orders'][0]['filled'] == '2'


def test_phase5_cancel_late_fill_then_exit_never_oversells(rig):
    event = rig.command()
    rig.follower.engine.tick()
    rig.follower_api.fill(rig.follower_api.posts[0]['client_order_id'], 1)
    rig.command('cancel', trade_id=event.trade_id)
    rig.follower_api.fill_during_cancel = 4
    assert rig.follower.engine.tick()[0]['state'] == 'cancel_pending'
    rig.restart_follower()
    assert rig.follower.engine.tick()[0]['state'] == 'invalidated'
    assert len(rig.follower_api.posts) == 1
    # Request more than the tracked late fill; the engine must cap the close.
    rig.command('exit', trade_id=event.trade_id, quantity=9)
    assert rig.follower.engine.tick()[0]['state'] == 'submitted'
    close = rig.follower_api.posts[-1]
    assert (close['side'], close['qty'], close['position_intent']) == ('sell', '4', 'sell_to_close')
    rig.follower_api.fill(close['client_order_id'], 4, 'filled')
    rig.restart_follower()
    assert rig.follower.engine.tick()[0]['state'] == 'settled'
    assert rig.follower.engine.tick() == []
    assert sum(Decimal(row['qty']) for row in rig.follower_api.posts if row['side'] == 'sell') == 4


def test_phase5_lost_broker_post_response_restarts_without_duplicate(rig):
    event = rig.command()
    rig.follower_api.lose_next_response = True
    assert rig.follower.engine.tick()[0] == {
        'trade_id': event.trade_id, 'state': 'reconcile_required', 'error': 'ReadTimeout'}
    assert rig.follower.engine.status()['orders'][0]['status'] == 'unknown'
    rig.restart_follower()
    rig.follower_api.lookup_hidden = True
    assert rig.follower.engine.tick()[0]['state'] == 'working'
    assert len(rig.follower_api.posts) == 1
    rig.restart_follower()
    rig.follower_api.lookup_hidden = False
    assert rig.follower.engine.tick()[0]['state'] == 'working'
    assert len(rig.follower_api.posts) == 1
    saved = rig.follower.engine.status()['orders'][0]
    assert saved['broker_id'] == rig.follower_api.orders[saved['cid']]['id']
    assert saved['status'] == 'new'
