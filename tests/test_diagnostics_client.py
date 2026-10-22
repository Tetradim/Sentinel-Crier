from datetime import datetime, timezone
import asyncio
import httpx
from crier.diagnostics_client import iso
from crier.intent_device import IntentDevice
from crier.trade_diagnostics import trade_report, _latency


def observation(stage, time=100000, offset=0, source='alpaca:iex'):
    return dict(stage=stage,observed_at=iso(time),clock_sampled_at=iso(time-100),clock_offset_ms=offset,clock_uncertainty_ms=2,quote=dict(source=source,quote_timestamp=iso(time+offset-100),bid='1',ask='2',last=None),quote_error=None)


def test_clock_corrected_latency_and_invalid_samples():
    sender=observation('sender',100000,100)
    receiver=observation('receiver',100150,0)
    assert _latency(sender,receiver)==(50,4)
    receiver['clock_sampled_at']=iso(0)
    assert _latency(sender,receiver)==(None,None)
    assert _latency(sender,observation('receiver',90000))==(None,None)


def test_events_never_blend_revisions_or_sources():
    def row(id,actor,obs,sequence):
        return dict(timestamp=obs['observed_at'],trade_id='t',event_id=id,stage='diagnostic_observation',details=dict(actor=actor,observation=obs,sequence=sequence))
    rows=[row('a','host',observation('sender'),1),row('a','r',observation('receiver',100050),1),row('b','r',observation('receiver',100100),2)]
    report=trade_report(rows)
    assert report['latest_event_id']=='b'
    assert report['premium_movement']['status']=='unavailable'
    assert report['events'][0]['premium_movement']['status']=='available'
    rows[1]['details']['observation']['quote']['source']='different'
    assert trade_report(rows)['events'][0]['premium_movement']['status']=='unavailable'


def test_quote_capture_uses_only_real_entitled_feed(tmp_path):
    device=IntentDevice(tmp_path)
    device.broker=type('Broker',(),{'data_headers':{'APCA-API-KEY-ID':'test'}})()
    async def run():
        async def handler(request):
            assert request.url.params['feed']=='opra'
            assert request.url.host=='data.alpaca.markets'
            return httpx.Response(403,json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            obs=observation('sender')
            obs['quote']=None
            await device.diagnostics.capture(client,{'asset':'option','symbol':'TEST'},obs)
            assert obs['quote'] is None
            assert obs['quote_error']=='market_data_http_403'
    asyncio.run(run())
def test_worker_persists_remote_evidence_and_finishes(tmp_path,monkeypatch):
    import json
    import time
    from types import SimpleNamespace
    device=IntentDevice(tmp_path)
    device.pair={'url':'http://localhost','token':'x'*32,'environment':'paper','role':'follower'}
    payload=dict(event_id='event',trade_id='trade',symbol='SPY',asset='stock')
    event=SimpleNamespace(**payload,model_dump_json=lambda:json.dumps(payload))
    device.diagnostics.observe(event,'receiver')
    stop=asyncio.Event()
    posted=[]
    async def handler(request):
        if request.url.path.endswith('/clock'):
            return httpx.Response(200,json={'server_time_ms':time.time()*1000})
        if request.method=='POST':
            posted.append(json.loads(request.content)['observation'])
            return httpx.Response(200,json={})
        stop.set()
        host=dict(posted[0],stage='sender')
        return httpx.Response(200,json={'observations':[{'actor':'host','observation':host},{'actor':'receiver-id','observation':posted[0]}]})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    asyncio.run(device.diagnostics.run(stop))
    with device.db() as db:
        row=db.execute('SELECT * FROM diagnostic_jobs').fetchone()
        assert row['done']==1
        assert row['attempts']==1
    report=device.trade_report('trade')
    assert set(report['events'][0]['observations'])=={'local','host','receiver-id'}
    assert posted[0]['quote_error']=='market_data_credentials_unavailable'
    # Received evidence remains available after reopening the device.
    reopened=IntentDevice(tmp_path)
    assert reopened.trade_report('trade')==report

def test_quote_price_bounds_and_empty_liquidity():
    import pytest
    from crier.trade_diagnostics import validate_quote, premium_comparison
    with pytest.raises(ValueError):
        validate_quote(dict(source='test',quote_timestamp=iso(100000),bid='1e999999999',ask='1e999999999'))
    assert premium_comparison({'ask':'0'},{'ask':'2'})['status']=='unavailable'

def test_clock_sample_midpoint_and_wall_jump(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import crier.diagnostics_client as module
    device=IntentDevice(tmp_path)
    device.pair={'url':'http://localhost','token':'x'*32,'environment':'paper','role':'host'}
    class Client:
        async def get(self,*args,**kwargs):
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'server_time_ms':1000120})
    walls=iter([1000,1000.040])
    monos=iter([10,10.040,10.040])
    monkeypatch.setattr(module,'time',SimpleNamespace(time=lambda:next(walls),monotonic=lambda:next(monos)))
    asyncio.run(device.diagnostics.sample_clock(Client(),device.pair))
    assert round(device.diagnostics.clock['offset'])==100
    assert round(device.diagnostics.clock['uncertainty'])==20
    walls=iter([1000,1001])
    monos=iter([10,10.040])
    asyncio.run(device.diagnostics.sample_clock(Client(),device.pair))
    assert device.diagnostics.clock is None

def test_real_relay_host_to_follower_diagnostics(tmp_path,monkeypatch):
    import time
    from fastapi import FastAPI
    from crier.intent_relay import IntentRelay, sync_router
    from test_intent_device import Engine
    relay=IntentRelay(tmp_path/'relay.sqlite')
    pair=relay.create('integration','paper')
    app=FastAPI()
    app.include_router(sync_router(relay,lambda:None))
    host=IntentDevice(tmp_path/'host')
    follower=IntentDevice(tmp_path/'follower')
    for device,role,token in ((host,'host',pair['host_token']),(follower,'follower',pair['follower_token'])):
        device.configure(dict(url='https://relay.test',token=token,environment='paper',role=role))
        device.engine=Engine()
        device.broker=type('DataCredentials',(),{'data_headers':{'APCA-API-KEY-ID':'integration-key','APCA-API-SECRET-KEY':'integration-secret'}})()
    asgi=httpx.ASGITransport(app=app)
    posts=[]
    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            if request.url.host=='data.alpaca.markets':
                assert request.url.params['feed']=='iex'
                return httpx.Response(200,json={'quote':{'t':iso(time.time()*1000-25),'bp':2.30,'ap':2.40}})
            response=await asgi.handle_async_request(request)
            if request.method=='POST' and request.url.path.endswith('/diagnostics'):
                posts.append(response.status_code)
            return response
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=Transport(),**kwargs))
    async def run():
        stop=asyncio.Event()
        async with httpx.AsyncClient() as client:
            await host.diagnostics.sample_clock(client,host.pair)
            await follower.diagnostics.sample_clock(client,follower.pair)
        event=host.command('enter',symbol='AAPL',asset='stock',quantity=1,limit_price='2.40')
        tasks=[asyncio.create_task(fn(stop)) for fn in (host.publish_loop,follower.receive_loop,host.diagnostics_loop,follower.diagnostics_loop)]
        try:
            for _ in range(160):
                report=follower.trade_report(event.trade_id)
                if report['premium_movement']['status']=='available':
                    break
                await asyncio.sleep(.05)
            else:
                raise AssertionError(str(report))
            assert report['latest_event_id']==event.event_id
            assert report['cross_device_latency_ms'] is not None
            assert report['clock_uncertainty_ms']>=0
            assert float(report['premium_movement']['change'])==0
            assert posts and all(status==200 for status in posts)
            exported=follower.export_trade(event.trade_id)
            for secret in ('integration-key','integration-secret',pair['host_token'],pair['follower_token']):
                assert secret not in exported
            assert follower.engine.events[0].event_id==event.event_id
        finally:
            stop.set()
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    asyncio.run(run())

def test_report_rejects_provider_error_unknown_feed_and_unbounded_clock():
    from crier.trade_diagnostics import _fresh_quote
    obs=observation('sender')
    obs['quote_error']='Stale at fetch completion'
    assert _fresh_quote(obs) is None
    obs['quote_error']=None
    obs['quote']['source']='alpaca:indicative'
    assert _fresh_quote(obs) is None
    obs['quote']['source']='alpaca:iex'
    obs['clock_uncertainty_ms']=30001
    assert _latency(obs,obs)==(None,None)
    obs['clock_uncertainty_ms']=2
    obs['clock_offset_ms']=604800001
    assert _latency(obs,obs)==(None,None)
