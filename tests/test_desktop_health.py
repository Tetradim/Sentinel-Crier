import asyncio
from types import SimpleNamespace
import httpx
import pytest
from crier.desktop_runtime import DesktopSession
from crier.intent_device import IntentDevice


def test_account_and_fill_checks_have_separate_scoped_evidence_and_restart_stops(tmp_path):
    calls=[]
    def response(request):
        calls.append(request)
        return httpx.Response(200,json={'id':'account-a'} if request.url.path.endswith('/account') else [])
    client=httpx.Client(transport=httpx.MockTransport(response))
    class Reader:
        def __init__(self,*args): self.client=client; self.environment='paper'
        def verify(self,environment):
            assert self.client.get('https://paper-api.alpaca.markets/v2/account').json()['id']=='account-a'
        def close(self): pass
    async def lookup(*args): return 'account-a'
    async def run():
        session=DesktopSession(tmp_path,start_workers=False,alerts_lookup=lookup,alerts_factory=Reader)
        await session.connect_alerts('paper','synthetic','synthetic')
        rows={r['component']:r for r in session.status()['health']}
        assert rows['broker']['state']==rows['fills']['state']=='healthy'
        assert rows['discord']['state']=='stopped'
        success=rows['fills']['last_success']
        await session.disconnect()
        assert all(r['state']=='stopped' for r in session.status()['health'])
        restarted=DesktopSession(tmp_path,start_workers=False)
        rows={r['component']:r for r in restarted.status()['health']}
        assert rows['fills']['state']=='stopped' and rows['fills']['last_success']==success
        assert all(r.method=='GET' for r in calls)
    try: asyncio.run(run())
    finally: client.close()


@pytest.mark.parametrize('result',[{'state':'reconcile_required'}, {'state':'waiting_for_reconciliation'},
                                  {'state':'cancel_pending','reconciliation_required':True}])
def test_execution_worker_cannot_report_healthy_while_reconciliation_is_required(tmp_path,result):
    async def run():
        observations=[]; stop=asyncio.Event(); loop=asyncio.get_running_loop()
        device=IntentDevice(tmp_path,observe=lambda *args:observations.append(args))
        def tick():
            loop.call_soon_threadsafe(stop.set); loop.call_soon_threadsafe(device.changed.set)
            return [result]
        device.engine=SimpleNamespace(tick=tick)
        await device.execute_loop(stop)
        assert observations==[('execution','blocked','reconciliation_required')]
    asyncio.run(run())


@pytest.mark.parametrize('status,expected',[(200,('healthy','checked')),(401,('blocked','authentication_failed')),(503,('degraded','connection_failed'))])
def test_relay_health_uses_actual_poll_outcome_without_extra_requests(tmp_path,monkeypatch,status,expected):
    from crier import intent_device
    async def run():
        stop=asyncio.Event(); observed=[]; calls=[]
        async def respond(request):
            if request.url.path.endswith(('/stream','/dashboard')): return httpx.Response(404)
            calls.append(request); asyncio.get_running_loop().call_later(.001,stop.set)
            return httpx.Response(status,json={'events':[]})
        original=httpx.AsyncClient
        monkeypatch.setattr(intent_device.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
        device=IntentDevice(tmp_path,observe=lambda *args:observed.append(args))
        device.pair=dict(url='https://synthetic.example.test',token='private-token',environment='paper',role='follower')
        device.engine=SimpleNamespace()
        await device.receive_loop(stop)
        assert observed==[('relay_receive',*expected)]
        assert len(calls)==1 and calls[0].method=='GET'
        assert 'private-token' not in repr(observed)
    asyncio.run(run())


def test_failed_health_write_is_visible_but_never_interrupts_broker_work(tmp_path,monkeypatch):
    import sqlite3
    session=DesktopSession(tmp_path,start_workers=False)
    def failed(*args): raise sqlite3.OperationalError('disk unavailable')
    monkeypatch.setattr(session.health,'record',failed)
    session.observe('broker','healthy','verified')
    assert session.status()['health_error']


def test_locked_diagnostics_database_does_not_delay_the_worker_loop(tmp_path):
    import sqlite3
    import time
    from contextlib import closing
    session=DesktopSession(tmp_path,start_workers=False)
    with closing(sqlite3.connect(session.health.path)) as other:
        other.execute('BEGIN IMMEDIATE')
        started=time.monotonic()
        session.observe('broker','healthy','verified')
        elapsed=time.monotonic()-started
        assert session.health_error
        assert elapsed<0.5
