import asyncio
import json
import httpx
import pytest
from crier.desktop_runtime import DesktopSession, discover_account
from crier.device_secrets import load_secret

PAIR = dict(url='https://relay.example', token='t'*40, environment='paper', role='follower')

class Broker:
    def __init__(self, environment, key, secret, account):
        self.environment = environment
        self.account = account
        self.closed = False
    def close(self): self.closed = True

async def account(environment, key, secret):
    return 'account-one'

def test_account_discovery_uses_selected_broker_and_checks_status():
    async def run():
        def handler(request):
            assert request.url.host == 'paper-api.alpaca.markets'
            assert request.headers['APCA-API-KEY-ID'] == 'key'
            return httpx.Response(200, json={'id':'account-one','status':'ACTIVE'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await discover_account('paper','key','secret',client=client) == 'account-one'
    asyncio.run(run())

def test_desktop_connection_is_paused_and_secrets_protected(tmp_path):
    async def run():
        session = DesktopSession(tmp_path, account_lookup=account, broker_factory=Broker, start_workers=False)
        await session.connect(json.dumps(PAIR), 'private-key', 'private-secret')
        assert not session.status()['execution']['settings']['enabled']
        assert session.status()['account'] == 'account-one'
        assert 'private-secret' not in json.dumps(session.status())
        saved = tmp_path/'desktop-credentials.secret'
        assert b'private-secret' not in saved.read_bytes()
        assert json.loads(load_secret(saved))['secret'] == 'private-secret'
        session.settings({'enabled':True})
        broker = session.broker
        await session.disconnect()
        assert broker.closed
        await session.connect('', '', '')
        assert not session.status()['execution']['settings']['enabled']
        await session.disconnect()
    asyncio.run(run())

def test_desktop_refuses_account_or_channel_switch(tmp_path):
    async def run():
        session = DesktopSession(tmp_path, account_lookup=account, broker_factory=Broker, start_workers=False)
        await session.connect(json.dumps(PAIR), 'key', 'secret')
        await session.disconnect()
        other = dict(PAIR, token='z'*40)
        with pytest.raises(ValueError, match='pinned'):
            await session.connect(json.dumps(other), 'key', 'secret')
        async def changed(*args): return 'account-two'
        session.account_lookup = changed
        with pytest.raises(ValueError, match='pinned'):
            await session.connect(json.dumps(PAIR), 'key', 'secret')
        assert not session.status()['connected']
    asyncio.run(run())

def test_failed_verification_does_not_persist_credentials(tmp_path):
    async def run():
        async def denied(*args): raise ValueError('Account unavailable')
        session = DesktopSession(tmp_path, account_lookup=denied, start_workers=False)
        with pytest.raises(ValueError):
            await session.connect(json.dumps(PAIR), 'key', 'secret')
        assert not (tmp_path/'desktop-credentials.secret').exists()
        assert not session.status()['connected']
    asyncio.run(run())

def test_live_requires_explicit_local_selection(tmp_path):
    async def run():
        session = DesktopSession(tmp_path, account_lookup=account, start_workers=False)
        with pytest.raises(ValueError, match='live'):
            await session.connect(json.dumps(dict(PAIR, environment='live')), 'key', 'secret')
    asyncio.run(run())

def test_ios_wire_event_reaches_desktop_broker_without_waiting_for_fill(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from crier.intent_relay import IntentRelay, sync_router
    from test_intent_relay import event
    from crier import intent_device

    class TradingBroker(Broker):
        def __init__(self, *args):
            super().__init__(*args)
            self.requests = []
            self.order = None
        def verify(self, environment):
            assert environment == self.environment
            return self.account
        def submit_checked(self, order, can_submit):
            assert can_submit()
            self.requests.append(order)
            self.order = dict(order, id='paper-order', status='accepted', filled_qty='0')
            return self.order
        def lookup(self, client_order_id): return self.order
        def cancel(self, order_id): self.order['status'] = 'canceled'

    async def run():
        relay = IntentRelay(tmp_path/'relay.sqlite3')
        app = FastAPI()
        app.include_router(sync_router(relay, lambda: None))
        channel = relay.create('iPhone to desktop', 'paper')
        pairing = dict(PAIR, token=channel['follower_token'])
        client_type = httpx.AsyncClient
        transport = httpx.ASGITransport(app=app)
        monkeypatch.setattr(intent_device.httpx, 'AsyncClient',
                            lambda **kwargs: client_type(transport=transport, **kwargs))
        session = DesktopSession(tmp_path/'desktop', account_lookup=account, broker_factory=TradingBroker)
        try:
            await session.connect(json.dumps(pairing), 'key', 'secret')
            session.settings({'enabled':True})
            # Same JSON contract as IntentEvent.make in the native iOS app.
            instruction = event(symbol='SPY261212C00750000', asset='option', quantity=2, limit_price='0.20')
            async with client_type(transport=transport, base_url=PAIR['url']) as client:
                response = await client.post('/api/sync/events', json=instruction.to_dict(),
                    headers={'Authorization':'Bearer '+channel['host_token']})
                assert response.status_code == 200
                async def received():
                    while not session.broker.requests:
                        await asyncio.sleep(.01)
                await asyncio.wait_for(received(), 5)
                order = session.broker.requests[0]
                assert (order['symbol'], order['qty'], order['limit_price'], order['side']) == (
                    'SPY261212C00750000', '2', '0.20', 'buy')
                assert session.broker.order['filled_qty'] == '0'
                await session.disconnect()
        finally:
            await session.disconnect()
    asyncio.run(run())
