import asyncio
import json
import httpx
import pytest
from crier.desktop_runtime import DesktopSession
from crier.device_secrets import load_secret


def test_alerts_read_only_discovery_baseline_restart_and_pin(tmp_path, monkeypatch):
    from crier import desktop_runtime as runtime
    requests = []
    identity = ['account-one']
    fills = []
    def handler(request):
        requests.append(request)
        assert request.method == 'GET'
        assert request.url.host == 'paper-api.alpaca.markets'
        if request.url.path == '/v2/account':
            return httpx.Response(200, json={'id': identity[0], 'trading_blocked': True})
        assert request.url.path == '/v2/account/activities/FILL'
        return httpx.Response(200, json=fills)
    sync_client, async_client = httpx.Client, httpx.AsyncClient
    monkeypatch.setattr(runtime.httpx, 'Client', lambda **kw: sync_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(runtime.httpx, 'AsyncClient', lambda **kw: async_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(runtime, 'IntentDevice', lambda *a: pytest.fail('Alerts must not create an intent device'))
    async def run():
        session = DesktopSession(tmp_path, start_workers=False)
        session.intent_publisher.configure('https://discord.com/api/webhooks/123/old-token', True)
        old_publisher = session.publisher
        from crier.alpaca import poll_once
        from test_alpaca import activity
        with sync_client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[]))) as client:
            poll_once(old_publisher.store, client, 'old-intent-account')
        with sync_client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[activity()]))) as client:
            poll_once(old_publisher.store, client, 'old-intent-account')
        old_history = old_publisher.store.history()
        assert len(old_history) == 1
        state = await session.connect_alerts('paper', 'private-key', 'private-secret')
        assert state['mode'] == 'alerts' and state['connected']
        assert state['alerts']['state'] == 'observing'
        assert session.device is None and session.tasks == []
        assert not session.publisher.status()['configured']
        assert not session.publisher.status()['enabled']
        assert session.publisher.store.history() == []
        fills.append(activity())
        await session.poll_alerts()
        assert len(session.publisher.store.history()) == 1
        sent = []
        def discord(request):
            assert request.url.host == 'discord.com' and request.method == 'POST'
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={'id':'123456'})
        with sync_client(transport=httpx.MockTransport(discord)) as client:
            assert not session.publisher.deliver(client)
            session.discord_configure('https://discord.com/api/webhooks/456/new-token', True)
            assert session.publisher.deliver(client)
            assert not session.publisher.deliver(client)
        assert len(sent) == 1
        assert old_publisher.store.history() == old_history
        assert old_publisher.destination['webhook'].endswith('old-token')
        assert not hasattr(session.broker, 'submit')
        assert not (tmp_path/'journal').exists()
        assert not (tmp_path/'desktop-credentials.secret').exists()
        saved = tmp_path/'desktop-alerts-credentials.secret'
        assert b'private-secret' not in saved.read_bytes()
        assert json.loads(load_secret(saved))['account'] == 'account-one'
        with pytest.raises(ValueError, match='Disconnect'):
            await session.connect_alerts('paper', '', '')
        with pytest.raises(ValueError, match='Disconnect'):
            await session.host('https://relay.example', 'paper')
        with pytest.raises(ValueError, match='Connect'):
            session.command('enter')
        broker = session.broker
        await session.disconnect()
        assert broker.client.is_closed and session.status()['mode'] == 'disconnected'
        restarted = DesktopSession(tmp_path, start_workers=False)
        with pytest.raises(ValueError, match='environment'):
            await restarted.connect_alerts('live', '', '', allow_live=True)
        identity[0] = 'account-two'
        with pytest.raises(ValueError, match='pinned'):
            await restarted.connect_alerts('paper', '', '')
        identity[0] = 'account-one'
        await restarted.connect_alerts('paper', '', '')
        assert not restarted.alert_state['enrolled']
        assert restarted.publisher.store.history()[0]['status'] == 'sent'
        assert len(restarted.publisher.store.history()) == 1
        await restarted.disconnect()
    asyncio.run(run())
    assert requests

@pytest.mark.parametrize('environment,key,secret,allow_live', [('live','key','secret',False), ('wrong','key','secret',False), ('paper','key','',False)])
def test_alerts_rejects_invalid_inputs_before_verification(tmp_path, environment, key, secret, allow_live):
    async def lookup(*args):
        pytest.fail('Invalid input reached account verification')
    async def run():
        session = DesktopSession(tmp_path, alerts_lookup=lookup, start_workers=False)
        with pytest.raises(ValueError):
            await session.connect_alerts(environment, key, secret, allow_live=allow_live)
        assert not session.status()['connected']
        assert not session.alerts_credentials.exists()
    asyncio.run(run())


def test_alerts_profile_failure_closes_client(tmp_path, monkeypatch):
    from crier import desktop_runtime as runtime
    brokers = []
    async def lookup(*args): return 'account'
    class Reader:
        def __init__(self, *args):
            self.closed = False
            brokers.append(self)
        def close(self): self.closed = True
    async def run():
        session = DesktopSession(tmp_path, alerts_lookup=lookup, alerts_factory=Reader, start_workers=False)
        monkeypatch.setattr(runtime, 'DiscordPublisher', lambda *args: (_ for _ in ()).throw(OSError('unwritable')))
        with pytest.raises(OSError):
            await session.connect_alerts('paper', 'key', 'secret')
        assert brokers[0].closed and session.broker is None
        assert session.publisher is session.intent_publisher
        assert not session.alerts_credentials.exists()
    asyncio.run(run())


def test_alerts_connect_serializes_and_disconnect_joins_worker(tmp_path, monkeypatch):
    from crier import desktop_runtime as runtime
    real_client = httpx.Client
    clients = []
    def client(**kwargs):
        result = real_client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={'id':'account'} if req.url.path == '/v2/account' else [])), **kwargs)
        clients.append(result)
        return result
    monkeypatch.setattr(runtime.httpx, 'Client', client)
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def lookup(*args):
            entered.set()
            await release.wait()
            return 'account'
        session = DesktopSession(tmp_path, alerts_lookup=lookup)
        first = asyncio.create_task(session.connect_alerts('paper','key','secret'))
        await entered.wait()
        assert not session.status()['connected']
        second = asyncio.create_task(session.connect_alerts('paper','key','secret'))
        release.set()
        await first
        with pytest.raises(ValueError, match='Disconnect'):
            await second
        tasks = list(session.tasks)
        assert len(tasks) == 1
        await asyncio.wait_for(session.disconnect(), 3)
        assert all(task.done() for task in tasks)
        assert all(client.is_closed for client in clients)
        assert session.status()['alerts']['state'] == 'stopped'
    asyncio.run(run())


def test_cancelled_alerts_start_waits_for_inflight_read_before_close(tmp_path, monkeypatch):
    import threading
    from crier import desktop_runtime as runtime
    entered, release = threading.Event(), threading.Event()
    clients = []
    real_client = httpx.Client
    def handler(request):
        if request.url.path == '/v2/account':
            entered.set()
            assert release.wait(3)
            return httpx.Response(200, json={'id':'account'})
        return httpx.Response(200, json=[])
    def client(**kwargs):
        result = real_client(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(result)
        return result
    monkeypatch.setattr(runtime.httpx, 'Client', client)
    async def lookup(*args): return 'account'
    async def run():
        session = DesktopSession(tmp_path, alerts_lookup=lookup, start_workers=False)
        starting = asyncio.create_task(session.connect_alerts('paper','key','secret'))
        assert await asyncio.to_thread(entered.wait, 3)
        starting.cancel()
        await asyncio.sleep(.02)
        assert not clients[0].is_closed
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await starting
        assert clients[0].is_closed
        assert session.status()['mode'] == 'disconnected'
        assert session.publisher is session.intent_publisher
    asyncio.run(run())


@pytest.mark.parametrize('response', [httpx.Response(401, json={'message':'denied'}), httpx.Response(200, json={'id':''}), httpx.Response(200, json=[])])
def test_failed_alerts_read_verification_never_saves_keys(tmp_path, monkeypatch, response):
    from crier import desktop_runtime as runtime
    real_client = httpx.AsyncClient
    monkeypatch.setattr(runtime.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(lambda request: response), **kw))
    async def run():
        session = DesktopSession(tmp_path, start_workers=False)
        with pytest.raises(ValueError, match='read access'):
            await session.connect_alerts('paper', 'key', 'secret')
        assert not session.status()['connected']
        assert not session.alerts_credentials.exists()
    asyncio.run(run())


def test_verified_live_read_account_with_unavailable_fills_is_honest(tmp_path, monkeypatch):
    from crier import desktop_runtime as runtime
    real_sync, real_async = httpx.Client, httpx.AsyncClient
    def handler(request):
        assert request.method == 'GET' and request.url.host == 'api.alpaca.markets'
        if request.url.path == '/v2/account':
            return httpx.Response(200, json={'id':'account-live', 'account_blocked':True, 'trading_blocked':True})
        return httpx.Response(503, json={})
    monkeypatch.setattr(runtime.httpx, 'AsyncClient', lambda **kw: real_async(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(runtime.httpx, 'Client', lambda **kw: real_sync(transport=httpx.MockTransport(handler), **kw))
    async def run():
        session = DesktopSession(tmp_path, start_workers=False)
        state = await session.connect_alerts('live','key','secret', allow_live=True)
        assert state['connected'] and state['environment'] == 'live'
        assert state['alerts']['state'] == 'reconnecting'
        assert 'reconnecting' in state['message'] and 'Disconnected' not in state['message']
        assert session.publisher.store.history() == []
        await session.disconnect()
    asyncio.run(run())
