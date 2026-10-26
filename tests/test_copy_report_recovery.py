import asyncio
from datetime import datetime, timezone, timedelta
import sqlite3
import time
import threading

import httpx
import pytest

from crier.intent_device import IntentDevice
from test_intent_engine import Broker, event


def device(folder):
    result=IntentDevice(folder,Broker())
    result.configure(dict(url='https://example.test',token='x'*40,environment='paper',role='follower'))
    return result


def test_telemetry_storage_contention_keeps_loop_responsive_and_recovers(tmp_path,monkeypatch):
    d=device(tmp_path); posted=[]
    original=httpx.AsyncClient
    def respond(request):
        posted.append(request.url.path)
        return httpx.Response(200,json={'stored':True})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    async def run():
        stop=asyncio.Event(); lock=sqlite3.connect(d.path); lock.execute('BEGIN IMMEDIATE')
        worker=asyncio.create_task(d.reporter.run(stop)); started=time.monotonic()
        try:
            await asyncio.sleep(.08)
            assert time.monotonic()-started<.5, 'Telemetry SQLite wait blocked the event loop'
            lock.rollback(); d.reporter.changed.set()
            for _ in range(150):
                if posted: break
                await asyncio.sleep(.02)
            assert '/api/sync/presence' in posted
        finally:
            lock.rollback(); lock.close(); stop.set(); d.reporter.changed.set()
            worker.cancel(); await asyncio.gather(worker,return_exceptions=True)
    asyncio.run(run())
    assert d.broker.sent==[]


@pytest.mark.parametrize('cause,expected',[('expired','expired'),('max_age','expired'),('max_quantity','quantity_unavailable'),('paused','entries_paused')])
def test_skipped_reason_survives_settlement_and_restart(tmp_path,cause,expected):
    d=device(tmp_path); d.engine.save_settings({'enabled':cause!='paused'})
    now=datetime.now(timezone.utc)
    values={}
    if cause=='expired': values=dict(created_at=(now-timedelta(seconds=20)).isoformat(),expires_at=(now-timedelta(seconds=10)).isoformat())
    elif cause=='max_age':
        d.engine.save_settings({'max_age_seconds':1})
        values=dict(created_at=(now-timedelta(seconds=5)).isoformat(),expires_at=(now+timedelta(seconds=5)).isoformat())
    elif cause=='max_quantity': d.engine.save_settings({'max_quantity':1})
    instruction=event(quantity=2,**values); d.engine.accept(instruction)
    if cause=='paused': d.engine.save_settings({'enabled':True})
    d.engine.tick(); assert not d.broker.sent
    report=d.reporter.collect()[0]
    assert (report['state'],report['reason'])==('not_submitted',expected)
    restored=device(tmp_path)
    report=restored.reporter.collect()[0]
    assert (report['state'],report['reason'])==('not_submitted',expected)
    assert restored.engine.tick()==[] and not restored.broker.sent


def test_metadata_transient_failure_recovers_without_reconnect(tmp_path,monkeypatch):
    from crier.copy_reports import MetadataRetry
    import crier.copy_reports as module
    d=device(tmp_path); d.engine.save_settings({'enabled':True}); d.engine.accept(event())
    now=[0.0]; calls=[]; d.reporter.metadata_retry=MetadataRetry(clock=lambda:now[0])
    def metadata(e):
        calls.append(e['event_id'])
        if len(calls)==1: raise ConnectionError('synthetic transient error')
        return dict(account='test-account',environment='paper',symbol=e['symbol'],asset=e['asset'],currency='USD',multiplier=1)
    d.broker.metadata=metadata
    async def run():
        stop=asyncio.Event(); intervals=0
        async def interval(coroutine,timeout):
            nonlocal intervals
            coroutine.close(); intervals+=1; now[0]+=15
            if intervals==3: stop.set()
            raise TimeoutError()
        with monkeypatch.context() as scoped:
            scoped.setattr(module.asyncio,'wait_for',interval)
            await d.reporter.metadata_loop(stop)
    asyncio.run(run())
    assert len(calls)==2 and len(d.reporter.metadata)==1 and not d.broker.sent


def test_skip_reason_is_committed_even_if_settlement_is_interrupted(tmp_path,monkeypatch):
    d=device(tmp_path); d.engine.save_settings({'enabled':True})
    now=datetime.now(timezone.utc)
    d.engine.accept(event(created_at=(now-timedelta(seconds=20)).isoformat(),expires_at=(now-timedelta(seconds=10)).isoformat()))
    def interrupted(*args,**kwargs): raise RuntimeError('synthetic crash before settlement')
    monkeypatch.setattr(d.engine,'_settle',interrupted)
    assert d.engine.tick()[0]['state']=='reconcile_required'
    restored=device(tmp_path)
    report=restored.reporter.collect()[0]
    assert (report['state'],report['reason'])==('not_submitted','expired')
    restored.engine.tick()
    assert restored.reporter.collect()[0]['reason']=='expired' and not restored.broker.sent


def test_metadata_backoff_is_capped_and_success_is_not_retried():
    from crier.copy_reports import MetadataRetry
    now=[0.0]; retry=MetadataRetry(clock=lambda:now[0])
    assert retry.begin('trade') and not retry.begin('trade')
    for delay in (5,10,20,40,80,160,300,300):
        retry.complete('trade',False)
        now[0]+=delay-.1; assert not retry.begin('trade')
        now[0]+=.1; assert retry.begin('trade')
    retry.complete('trade',True); now[0]+=10000
    assert not retry.begin('trade')


def test_disconnect_drains_metadata_read_without_caching_late_binding(tmp_path):
    d=device(tmp_path); d.engine.accept(event())
    entered=threading.Event(); release=threading.Event()
    def metadata(e):
        entered.set()
        assert release.wait(3)
        return dict(account='test-account',environment='paper',symbol=e['symbol'],asset=e['asset'],currency='USD',multiplier=1)
    d.broker.metadata=metadata
    async def run():
        stop=asyncio.Event(); task=asyncio.create_task(d.reporter.metadata_loop(stop))
        try:
            for _ in range(100):
                if entered.is_set(): break
                await asyncio.sleep(.01)
            assert entered.is_set()
            stop.set(); task.cancel(); await asyncio.sleep(.03)
            assert not task.done(), 'A broker client may close only after its read drains'
        finally:
            release.set(); stop.set(); task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        assert not d.reporter.metadata
    asyncio.run(run())
