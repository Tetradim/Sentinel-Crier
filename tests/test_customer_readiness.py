import asyncio
import json
import httpx
import pytest
from crier.customer_readiness import connection_summary, probe_connection
from crier.intent_broker import AlpacaIntentBroker

def synthetic_reader(broker, environment, account, cancelled, *, require_trading):
    return broker.verify(environment)


PAIR = {'url': 'https://relay.example', 'token': 'x' * 32, 'environment': 'paper', 'role': 'host'}


def dashboard(**changes):
    return dict(version=1, channel_id='synthetic', environment='paper', role='host', actor='host',
                generated_at='2026-10-27T12:00:00Z', members=[], events=[], statuses=[], diagnostics=[], truncated=False, **changes)


def test_summary_uses_relay_and_reconciliation_evidence():
    state = dict(connected=True, mode='trade', pair={'role':'host','environment':'paper'},
                 transport='connecting', execution={'settings':{'enabled':False}, 'orders':[]}, health=[])
    assert connection_summary(state)['title'] == 'Connecting'
    state['transport'] = 'push'
    state['health'] = [{'component':'broker','state':'healthy'}, {'component':'relay_send','state':'healthy'}]
    assert connection_summary(state)['title'] == 'Hosting'
    state['health'] = [{'component':'relay_send','state':'degraded'}]
    assert connection_summary(state)['title'] == 'Reconnecting'
    state['execution']['orders'] = [{'status':'unknown','account':'do-not-display'}]
    assert connection_summary(state)['title'] == 'Needs reconciliation'
    assert 'do-not-display' not in json.dumps(connection_summary(state))
    state['connected'] = False
    assert connection_summary(state)['title'] == 'Needs reconciliation'


def test_summary_disconnected_alerts_following_and_blocked():
    assert connection_summary({'connected':False})['title'] == 'Disconnected'
    assert connection_summary({'connected':True,'mode':'alerts','alerts':{'state':'running'}})['title'] == 'Monitoring alerts'
    state = dict(connected=True, mode='trade', pair={'role':'follower'}, transport='poll', health=[{'component':'broker','state':'healthy'}, {'component':'relay_receive','state':'healthy'}])
    assert connection_summary(state)['title'] == 'Following'
    state['health'] = [{'component':'execution','state':'blocked'}]
    assert connection_summary(state)['title'] == 'Needs reconciliation'


def test_probe_only_reads_account_and_dashboard():
    requests=[]
    def broker_handler(request):
        requests.append(request)
        return httpx.Response(200,json={'id':'synthetic-account','status':'ACTIVE'})
    def relay_handler(request):
        requests.append(request)
        assert request.headers['Authorization'] == 'Bearer ' + PAIR['token']
        return httpx.Response(200,json=dashboard())
    with httpx.Client(transport=httpx.MockTransport(broker_handler)) as sync:
        broker=AlpacaIntentBroker('paper','key','secret','synthetic-account',client=sync)
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(relay_handler)) as client:
                return await probe_connection(broker,'paper','synthetic-account',PAIR,client=client,account_reader=synthetic_reader)
        result=asyncio.run(run())
    assert result['ready'] is True and result['delivery'] == 'not_tested'
    assert [(r.method,r.url.path) for r in requests] == [('GET','/v2/account'),('GET','/api/sync/dashboard')]
    assert not any(value in json.dumps(result) for value in ['synthetic-account',PAIR['token'],'secret'])


@pytest.mark.parametrize('case',['403','timeout','schema','environment','oversize','redirect'])
def test_probe_relay_failures_are_safe(case):
    class Broker:
        environment='paper'
        def verify(self,environment): return 'synthetic-account'
    def handler(request):
        if case=='timeout': raise httpx.ReadTimeout('private token secret',request=request)
        if case=='403': return httpx.Response(403,text='private token secret')
        if case=='redirect': return httpx.Response(302,headers={'location':'https://evil.example'})
        if case=='oversize': return httpx.Response(200,content=b' '*(256*1024+1))
        data=dashboard()
        if case=='schema': data['members']='private token secret'
        if case=='environment': data['environment']='live'
        return httpx.Response(200,json=data)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await probe_connection(Broker(),'paper','synthetic-account',PAIR,client=client,account_reader=synthetic_reader)
    result=asyncio.run(run())
    assert result['ready'] is False
    assert result['rows'][1]['status'] == 'failed'
    assert 'private token secret' not in json.dumps(result)


@pytest.mark.parametrize('verified',[None,'different'])
def test_probe_cannot_pass_unverified_identity(verified):
    class Broker:
        def verify(self,environment): return verified
    result=asyncio.run(probe_connection(Broker(),'paper','synthetic-account',account_reader=synthetic_reader))
    assert result['ready'] is False
    assert result['rows'][0]['status'] == 'failed'
    assert result['rows'][1]['status'] == 'not_configured'


def test_summary_recognizes_actual_alerts_observing_state():
    assert connection_summary({'connected':True,'mode':'alerts','alerts':{'state':'observing'}})['title'] == 'Monitoring alerts'


@pytest.mark.parametrize('account',['x'*101,'bad\x00account'])
def test_probe_refuses_malformed_account_identity(account):
    class Broker:
        def verify(self,environment): return account
    result=asyncio.run(probe_connection(Broker(),'paper',account,account_reader=synthetic_reader))
    assert result['ready'] is False


def test_summary_health_storage_failure_cannot_look_ready():
    state=dict(connected=True,mode='trade',pair={'role':'host'},transport='push',health_error=True)
    assert connection_summary(state)['title'] == 'Reconnecting'


def test_idle_host_relay_with_healthy_broker_is_hosting():
    state = dict(connected=True, mode='trade', pair={'role':'host'}, transport='push',
                 health=[{'component':'broker','state':'healthy'},
                         {'component':'relay_send','state':'idle','reason':'no_work'}],
                 execution={'settings':{'enabled':False},'orders':[]})
    summary=connection_summary(state)
    assert summary['title'] == 'Hosting'
    assert 'paused' in summary['detail']


@pytest.mark.parametrize('health', [[], [{'component':'relay_send','state':'idle','reason':'no_work'}],
    [{'component':'broker','state':'healthy'}]])
def test_missing_trade_health_is_conservative(health):
    state=dict(connected=True,mode='trade',pair={'role':'host'},transport='push',health=health)
    assert connection_summary(state)['title'] == 'Reconnecting'


@pytest.mark.parametrize('relay_state',['blocked','degraded','stopped','unknown'])
def test_bad_host_relay_health_never_looks_hosting(relay_state):
    state=dict(connected=True,mode='trade',pair={'role':'host'},transport='poll',health=[
        {'component':'broker','state':'healthy'},{'component':'relay_send','state':relay_state}])
    assert connection_summary(state)['title'] == 'Reconnecting'



def test_production_account_reader_owns_pinned_deadline_transport(monkeypatch):
    import threading
    import types
    import crier.customer_readiness as readiness
    from crier.updates import _DeadlineIO
    records=[]
    class Transport(httpx.BaseTransport):
        def __init__(self, **kwargs):
            records.append(kwargs)
            self._pool=types.SimpleNamespace(_network_backend=types.SimpleNamespace(connect_tcp=lambda:None))
        def handle_request(self,request):
            assert isinstance(self._pool._network_backend,_DeadlineIO)
            assert self._pool._network_backend.cancelled is cancelled
            records.append(request)
            return httpx.Response(200,json={'id':'synthetic-account','status':'ACTIVE','trading_blocked':False,'account_blocked':False})
        def close(self): records.append('closed')
    with httpx.Client(headers={'APCA-API-KEY-ID':'key','APCA-API-SECRET-KEY':'secret','Cookie':'private-cookie','X-Private':'private'}) as original:
        broker=types.SimpleNamespace(client=original,environment='paper',url='https://evil.example')
        cancelled=threading.Event()
        monkeypatch.setattr(readiness.httpx,'HTTPTransport',Transport)
        assert readiness._bounded_account(broker,'paper','synthetic-account',cancelled) == 'synthetic-account'
        assert not original.is_closed
    request=next(item for item in records if isinstance(item,httpx.Request))
    assert records[0] == {'trust_env':False,'retries':0}
    assert str(request.url)=='https://paper-api.alpaca.markets/v2/account' and request.method=='GET'
    assert request.headers['Accept-Encoding']=='identity'
    assert 'cookie' not in request.headers and 'x-private' not in request.headers
    assert records[-1]=='closed'


@pytest.mark.parametrize('case',['oversize','redirect','encoding','wrong_identity','blocked','string_flag'])
def test_bounded_account_rejects_bad_responses(monkeypatch,case):
    import threading
    import types
    import crier.customer_readiness as readiness
    class Transport(httpx.BaseTransport):
        def __init__(self,**kwargs):
            self._pool=types.SimpleNamespace(_network_backend=types.SimpleNamespace(connect_tcp=lambda:None))
        def handle_request(self,request):
            if case=='oversize': return httpx.Response(200,content=b' '*(128*1024+1))
            if case=='redirect': return httpx.Response(302,headers={'Location':'https://evil.example'})
            if case=='encoding': return httpx.Response(200,headers={'Content-Encoding':'unknown'},content=b'{}')
            row={'id':'synthetic-account','status':'ACTIVE','trading_blocked':False,'account_blocked':False}
            if case=='wrong_identity': row['id']='other'
            if case=='blocked': row['trading_blocked']=True
            if case=='string_flag': row['trading_blocked']='false'
            return httpx.Response(200,json=row)
    with httpx.Client(headers={'Authorization':'Bearer synthetic'}) as original:
        monkeypatch.setattr(readiness.httpx,'HTTPTransport',Transport)
        with pytest.raises(Exception):
            readiness._bounded_account(types.SimpleNamespace(client=original,environment='paper'),'paper','synthetic-account',threading.Event())


def test_account_reader_cancellation_drains_worker_without_closing_broker():
    import threading
    entered=threading.Event(); finished=threading.Event()
    def reader(broker, environment, account, cancelled, *, require_trading):
        entered.set()
        assert cancelled.wait(2)
        finished.set()
        raise ValueError('cancelled')
    async def run():
        task=asyncio.create_task(probe_connection(object(),'paper','synthetic-account',account_reader=reader))
        assert await asyncio.to_thread(entered.wait,2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert finished.is_set()
    asyncio.run(run())


def test_unsupported_broker_fails_closed_without_verify():
    calls=[]
    class Broker:
        def verify(self,environment): calls.append(environment); return 'synthetic-account'
    result=asyncio.run(probe_connection(Broker(),'paper','synthetic-account'))
    assert not result['ready']
    assert not calls



def test_bounded_account_stalled_dns_uses_total_deadline(monkeypatch):
    import threading
    import time
    import types
    import crier.customer_readiness as readiness
    import crier.updates as updates
    entered=threading.Event(); release=threading.Event()
    def resolve(*args,**kwargs):
        entered.set(); release.wait(2)
        return []
    with httpx.Client(headers={'Authorization':'Bearer synthetic'}) as original:
        monkeypatch.setattr(updates.socket,'getaddrinfo',resolve)
        monkeypatch.setattr(readiness,'ACCOUNT_TIMEOUT',0.7)
        started=time.monotonic()
        try:
            with pytest.raises(Exception):
                readiness._bounded_account(types.SimpleNamespace(client=original,environment='paper'),'paper','synthetic-account',threading.Event())
            assert entered.is_set()
            assert time.monotonic()-started < 1.5
        finally: release.set()


def test_bounded_account_trickled_headers_exceed_total_deadline(monkeypatch):
    import threading
    import types
    import crier.customer_readiness as readiness
    clock=[0.0]
    class Transport(httpx.BaseTransport):
        def __init__(self,**kwargs):
            self._pool=types.SimpleNamespace(_network_backend=types.SimpleNamespace(connect_tcp=lambda:None))
        def handle_request(self,request):
            clock[0]=11.0
            return httpx.Response(200,json={'id':'synthetic-account','status':'ACTIVE','trading_blocked':False,'account_blocked':False})
    with httpx.Client(headers={'Authorization':'Bearer synthetic'}) as original:
        monkeypatch.setattr(readiness.httpx,'HTTPTransport',Transport)
        monkeypatch.setattr(readiness.time,'monotonic',lambda:clock[0])
        with pytest.raises(ValueError,match='timed out'):
            readiness._bounded_account(types.SimpleNamespace(client=original,environment='paper'),'paper','synthetic-account',threading.Event())


def test_alert_account_read_does_not_require_trade_permission(monkeypatch):
    import threading
    import types
    import crier.customer_readiness as readiness
    class Transport(httpx.BaseTransport):
        def __init__(self,**kwargs):
            self._pool=types.SimpleNamespace(_network_backend=types.SimpleNamespace(connect_tcp=lambda:None))
        def handle_request(self,request):
            return httpx.Response(200,json={'id':'synthetic-account','status':'BLOCKED','trading_blocked':True})
    with httpx.Client(headers={'Authorization':'Bearer synthetic'}) as original:
        monkeypatch.setattr(readiness.httpx,'HTTPTransport',Transport)
        assert readiness._bounded_account(types.SimpleNamespace(client=original,environment='paper'),'paper','synthetic-account',threading.Event(),require_trading=False)=='synthetic-account'

