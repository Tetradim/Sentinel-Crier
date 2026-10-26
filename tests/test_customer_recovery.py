import asyncio
import json
import httpx
import pytest
from crier.intent_device import IntentDevice
from crier.intent_engine import IntentEngine
from test_intent_device import device
from test_intent_relay import event


def test_receiver_conflict_and_environment_do_not_block_next_event(tmp_path, monkeypatch):
    from crier import intent_device
    d = device(tmp_path)
    d.pair['role'] = 'follower'
    d.engine = IntentEngine(tmp_path/'engine.sqlite3', object())
    first = event()
    conflict = first.model_copy(update={'limit_price': first.limit_price + 1})
    wrong_environment = event(environment='live')
    good = event()
    items = [first, conflict, wrong_environment, good]
    original = httpx.AsyncClient
    async def run():
        stop = asyncio.Event()
        async def respond(request):
            await asyncio.sleep(.001)
            if request.url.path.endswith(('/stream','/dashboard')): return httpx.Response(404)
            if int(request.url.params['after']) == 0:
                return httpx.Response(200, json={'events': [{'cursor': i+1, 'event': e.to_dict()} for i,e in enumerate(items)]})
            stop.set()
            return httpx.Response(200,json={'events': []})
        monkeypatch.setattr(intent_device.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
        await asyncio.wait_for(d.receive_loop(stop), 2)
    asyncio.run(run())
    with d.db() as db:
        assert db.execute('SELECT cursor FROM cursors').fetchone()[0] == 4
        assert db.execute('SELECT COUNT(*) FROM quarantined_events').fetchone()[0] == 2
    assert len(d.engine.status()['trades']) == 2


def test_definitive_rejection_does_not_block_later_outgoing(tmp_path, monkeypatch):
    from crier import intent_device
    d = device(tmp_path)
    rejected = d.command('enter',symbol='AAPL',asset='stock',quantity=1,limit_price='1')
    delivered = d.command('enter',symbol='MSFT',asset='stock',quantity=1,limit_price='2')
    original = httpx.AsyncClient
    async def run():
        stop=asyncio.Event()
        async def respond(request):
            if json.loads(request.content)['event_id'] == rejected.event_id:
                return httpx.Response(422, json={'detail':'invalid'})
            stop.set()
            return httpx.Response(200,json={'ok':True})
        monkeypatch.setattr(intent_device.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
        await asyncio.wait_for(d.publish_loop(stop),2)
    asyncio.run(run())
    with d.db() as db:
        states={r['id']:r['state'] for r in db.execute('SELECT * FROM outgoing')}
    assert states[rejected.event_id]=='rejected'
    assert states[delivered.event_id]=='sent'
    assert d.status()['delivery']['rejected'] == 1

def test_browser_host_receive_and_receiver_revoke_without_exposing_tokens(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from crier.intent_relay import IntentRelay
    from crier.quick_connect import ConnectionService, connection_router
    from crier.intent_device import IntentDevice
    from crier.intent_routes import device_router
    from crier import connection_client
    relay=IntentRelay(tmp_path/'relay.sqlite3')
    service=ConnectionService(relay)
    remote=FastAPI();remote.include_router(connection_router(service,enabled=True))
    original=httpx.AsyncClient
    monkeypatch.setattr(connection_client.httpx,'AsyncClient',lambda **kw: original(transport=httpx.ASGITransport(app=remote),**kw))
    host=FastAPI(); host.include_router(device_router(IntentDevice(tmp_path/'host'),lambda:None))
    follower=FastAPI(); follower.include_router(device_router(IntentDevice(tmp_path/'follower'),lambda:None))
    with TestClient(host) as h, TestClient(follower) as f:
        response=h.post('/api/device/connect/host',json={'origin':'https://relay.example','environment':'paper'})
        assert response.status_code==200
        assert 'token' not in response.text
        invite=response.json()['invitation']
        joined=f.post('/api/device/connect/receive',json={'invitation':invite})
        assert joined.status_code==200
        assert joined.json()['pair']['role']=='follower'
        assert 'token' not in joined.text
        rows=h.get('/api/device/receivers').json()
        assert len(rows)==1
        assert f.get('/api/device/receivers').status_code==422
        assert h.post('/api/device/receivers/'+rows[0]['id']+'/revoke').status_code==200
        assert h.get('/api/device/receivers').json()[0]['revoked']==1
        assert f.post('/api/device/connect/receive',json={}).status_code==200


def test_auth_failure_retains_pending_instructions_and_rejected_retry_identity(tmp_path,monkeypatch):
    from crier import intent_device
    d=device(tmp_path)
    instruction=d.command('enter',symbol='AAPL',asset='stock',quantity=1,limit_price='1')
    original=httpx.AsyncClient
    async def run():
        stop=asyncio.Event()
        async def respond(request):
            stop.set()
            return httpx.Response(401,json={'detail':'unauthorized'})
        monkeypatch.setattr(intent_device.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
        await d.publish_loop(stop)
    asyncio.run(run())
    assert d.outgoing()[0]['id']==instruction.event_id
    assert 'rejected' in d.message.lower()
    with d.db() as db: db.execute("UPDATE outgoing SET state='rejected'")
    d.retry_rejected()
    assert d.outgoing()[0]['id']==instruction.event_id
    assert len(d.engine.events)==2 # original accept and safe local idempotent publisher accept

def test_same_account_rotation_keeps_pending_instruction_pricing_and_identity(tmp_path):
    from crier.desktop_runtime import DesktopSession
    from crier.device_secrets import load_secret
    from test_desktop import Broker,account,PAIR
    async def run():
        session=DesktopSession(tmp_path,account_lookup=account,broker_factory=Broker,start_workers=False)
        await session.connect(json.dumps(PAIR),'old-key','old-secret')
        instruction=event()
        session.device.engine.accept(instruction)
        session.settings({'max_slippage_amount':'0.031','max_quantity':3})
        journal=session.device.engine.path
        await session.disconnect()
        await session.connect('','new-key','new-secret')
        state=session.status()
        assert session.device.engine.path==journal
        assert state['execution']['trades'][0]['id']==instruction.trade_id
        assert state['execution']['settings']['max_slippage_amount']=='0.031'
        assert state['execution']['settings']['max_quantity']==3
        assert not state['execution']['settings']['enabled']
        assert json.loads(load_secret(session.credentials))['key']=='new-key'
        await session.disconnect()
    asyncio.run(run())

def test_invalid_connection_response_never_reflects_token(tmp_path):
    from crier.connection_client import ConnectionClient
    private='private-pairing-token-'+'t'*40
    client=ConnectionClient(tmp_path/'pair.secret')
    with pytest.raises(ValueError) as error:
        client.store('https://relay.example',dict(token=private,environment='paper',role='invalid'),'host')
    assert private not in str(error.value)


def test_discord_shutdown_does_not_start_new_delivery_after_poll(tmp_path):
    from crier.desktop_runtime import DesktopSession
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        stop=asyncio.Event()
        async def poll(): stop.set()
        session.poll_alerts=poll
        def deliver(client): raise AssertionError('No new delivery after stopping')
        session.publisher.deliver=deliver
        await session.discord_loop(stop)
    asyncio.run(run())
