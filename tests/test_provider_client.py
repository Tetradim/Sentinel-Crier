import asyncio
import httpx
import pytest
from crier.provider_client import ProviderClient, validate_service

BASE='https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth'
OWNER='12345678-1234-1234-1234-123456789abc'

def test_service_pin():
    assert validate_service(BASE)==BASE
    for bad in [BASE+'/',BASE+'/evil',BASE.replace('https:','http:'),BASE.replace('a'*20,'A'*20)]:
        with pytest.raises(ValueError): validate_service(bad)

def test_login_flow_one_use(tmp_path):
    calls=[]
    def respond(r):
        calls.append(r)
        if r.url.path.endswith('/auth/login'):
            return httpx.Response(200,json=dict(access_token='jwt',refresh_token='refresh',expires_in=3600,token_type='bearer',user={'id':OWNER}))
        if r.url.path.endswith('/oauth/begin'):
            return httpx.Response(200,json=dict(flow='x'*43,expires_at=200,launch_url=BASE+'/oauth/browser?ticket='+'t'*43))
        if r.url.path.endswith('/oauth/status'): return httpx.Response(200,json={'stage':'ready'})
        return httpx.Response(200,json=dict(provider='alpaca',environment='paper',purpose='alerts',account_id=OWNER,credential='bearer',scopes=[],guild_id='',channel_id=''))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client=ProviderClient(BASE,tmp_path/'session.secret',client=http,clock=lambda:100)
            await client.login('a@b.c','password')
            assert await client.begin('alpaca','alerts','paper')==BASE+'/oauth/browser?ticket='+'t'*43
            grant=await client.complete('sentinelcrier://oauth/complete?flow='+'x'*43)
            assert grant['credential']=='bearer'
            with pytest.raises(ValueError): await client.complete('sentinelcrier://oauth/complete?flow='+'x'*43)
            await client.logout()
            assert not (tmp_path/'session.secret').exists()
    asyncio.run(run())
    assert len(calls)==4


def test_late_login_after_logout_is_discarded(tmp_path):
    async def run():
        entered,release=asyncio.Event(),asyncio.Event()
        async def response(r):
            entered.set(); await release.wait()
            return httpx.Response(200,json=dict(access_token='jwt',refresh_token='refresh',expires_in=3600,token_type='bearer',user={'id':OWNER}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            client=ProviderClient(BASE,tmp_path/'session.secret',client=http)
            login=asyncio.create_task(client.login('a@b.c','pw'))
            await entered.wait(); await client.logout(); release.set()
            with pytest.raises(ValueError,match='session changed'): await login
            assert client.session is None and not client.path.exists()
    asyncio.run(run())


def test_ambiguous_redemption_is_never_retried(tmp_path):
    from crier.oauth_return import OAuthReturnContext,PendingOAuthReturn
    calls=[]
    def response(r):
        calls.append(r.url.path)
        if r.url.path.endswith('/status'): return httpx.Response(200,json={'stage':'ready'})
        raise httpx.ReadTimeout('private-provider-token')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            client=ProviderClient(BASE,tmp_path/'session.secret',client=http,clock=lambda:100)
            client.session=dict(access_token='jwt',user={'id':OWNER})
            client.context=OAuthReturnContext(OWNER,'alpaca','paper','alerts')
            client.flow='x'*43; client.proof='p'*43
            client.pending=PendingOAuthReturn(client.flow,client.context,expires_at=200)
            with pytest.raises(ValueError,match='could not be confirmed'):
                await client.complete('sentinelcrier://oauth/complete?flow='+'x'*43)
            with pytest.raises(ValueError,match='No pending'):
                await client.complete('sentinelcrier://oauth/complete?flow='+'x'*43)
    asyncio.run(run())
    assert len(calls)==2


def test_bearer_headers_exclusive():
    from crier.intent_broker import alpaca_headers,AlpacaIntentBroker
    assert alpaca_headers(bearer='token')=={'Authorization':'Bearer token'}
    with pytest.raises(ValueError): alpaca_headers('key','secret',bearer='token')
    requests=[]
    def respond(r):
        requests.append(r)
        assert r.headers['Authorization']=='Bearer token'
        assert 'APCA-API-KEY-ID' not in r.headers and 'APCA-API-SECRET-KEY' not in r.headers
        return httpx.Response(200,json={'id':OWNER,'status':'ACTIVE'})
    with httpx.Client(transport=httpx.MockTransport(respond),headers=alpaca_headers(bearer='token')) as http:
        broker=AlpacaIntentBroker('paper','','',OWNER,client=http,bearer='token')
        assert broker.verify('paper')==OWNER
    assert len(requests)==1

def test_parallel_begin_never_replaces_pending_context(tmp_path):
    async def run():
        entered,release=asyncio.Event(),asyncio.Event()
        async def respond(r):
            entered.set(); await release.wait()
            return httpx.Response(200,json=dict(flow='x'*43,expires_at=200,launch_url=BASE+'/oauth/browser?ticket='+'t'*43))
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client=ProviderClient(BASE,tmp_path/'session.secret',client=http,clock=lambda:100)
            client.session=dict(access_token='jwt',user={'id':OWNER})
            begin=asyncio.create_task(client.begin('alpaca','alerts','paper'))
            await entered.wait()
            with pytest.raises(ValueError,match='Cancel'): await client.begin('discord','alerts','live')
            release.set(); await begin
            assert client.context.provider=='alpaca' and client.context.environment=='paper'
    asyncio.run(run())


@pytest.mark.parametrize('stage',['begin','status','redeem'])
def test_cancel_discards_inflight_provider_response(tmp_path,stage):
    from crier.oauth_return import OAuthReturnContext,PendingOAuthReturn
    async def run():
        entered,release=asyncio.Event(),asyncio.Event()
        calls=[]
        async def respond(request):
            route=request.url.path.rsplit('/',1)[-1]; calls.append(route)
            if route==stage:
                entered.set(); await release.wait()
            if route=='cancel': return httpx.Response(200,json={'cancelled':True})
            if route=='begin': return httpx.Response(200,json=dict(flow='x'*43,expires_at=200,launch_url=BASE+'/oauth/browser?ticket='+'t'*43))
            if route=='status': return httpx.Response(200,json={'stage':'ready'})
            return httpx.Response(200,json=dict(provider='alpaca',environment='paper',purpose='alerts',account_id=OWNER,credential='bearer',scopes=[],guild_id='',channel_id=''))
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client=ProviderClient(BASE,tmp_path/'session.secret',client=http,clock=lambda:100)
            client.session=dict(access_token='jwt',user={'id':OWNER})
            if stage=='begin': task=asyncio.create_task(client.begin('alpaca','alerts','paper'))
            else:
                client.context=OAuthReturnContext(OWNER,'alpaca','paper','alerts')
                client.flow='x'*43; client.proof='p'*43
                client.pending=PendingOAuthReturn(client.flow,client.context,expires_at=200)
                task=asyncio.create_task(client.complete('sentinelcrier://oauth/complete?flow='+'x'*43))
            await entered.wait(); await client.cancel(); release.set()
            with pytest.raises(ValueError,match='session changed'): await task
            assert client.pending is None and client.proof is None
            if stage=='status': assert 'redeem' not in calls
    asyncio.run(run())
