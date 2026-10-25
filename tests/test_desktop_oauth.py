import asyncio
import json
from types import SimpleNamespace
import pytest
from crier.desktop_runtime import DesktopSession
from crier.device_secrets import load_secret,save_secret
from crier.desktop_oauth_return import enqueue_return,take_returns

OWNER='12345678-1234-1234-1234-123456789abc'

def test_uri_inbox_bounded_and_strict(tmp_path):
    uri='sentinelcrier://oauth/complete?flow='+'x'*43
    with pytest.raises(ValueError): enqueue_return(tmp_path,uri+'&credential=bad')
    for i in range(16): enqueue_return(tmp_path,uri)
    with pytest.raises(ValueError): enqueue_return(tmp_path,uri)
    assert take_returns(tmp_path)==[uri]*16
    assert take_returns(tmp_path)==[]


def test_uri_inbox_publishes_only_closed_files(tmp_path,monkeypatch):
    import crier.desktop_oauth_return as inbox
    original=inbox.os.replace
    uri='sentinelcrier://oauth/complete?flow='+'x'*43
    def replace(source,target):
        assert source.suffix=='.pending' and target.suffix=='.return'
        assert take_returns(tmp_path)==[]
        assert source.read_text() == uri
        original(source,target)
    monkeypatch.setattr(inbox.os,'replace',replace)
    enqueue_return(tmp_path,uri)
    assert take_returns(tmp_path)==[uri]


def test_uri_inbox_locked_delete_does_not_crash_poll(tmp_path,monkeypatch):
    from pathlib import Path
    uri='sentinelcrier://oauth/complete?flow='+'x'*43
    enqueue_return(tmp_path,uri)
    original=Path.unlink
    def locked(path,*args,**kwargs):
        if path.suffix=='.return': raise PermissionError('sharing violation')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',locked)
    assert take_returns(tmp_path)==[uri]


def test_install_only_verified_disconnected_and_pinned(tmp_path):
    verified=[]
    async def lookup(env,key,secret,*,bearer):
        verified.append((env,key,secret,bearer))
        return OWNER
    async def run():
        session=DesktopSession(tmp_path,start_workers=False,alerts_lookup=lookup)
        grant=dict(provider='alpaca',purpose='alerts',environment='paper',credential='bearer',account_id=OWNER)
        async def complete(uri): return grant
        session.oauth=SimpleNamespace(generation=0,complete=complete,base='https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth',session={'user':{'id':OWNER}})
        result=await session.provider_complete('synthetic-return')
        assert 'saved' in result['message']
        assert session.broker is None and session.device is None and not session.discord_authorized
        saved=json.loads(load_secret(session.alerts_credentials))
        assert saved['bearer']=='bearer' and saved['key']=='' and saved['account']==OWNER
        grant['account_id']='other'
        with pytest.raises(ValueError,match='verification mismatch'): await session.provider_complete('synthetic-return')
        assert json.loads(load_secret(session.alerts_credentials))==saved
        session.broker=object()
        with pytest.raises(ValueError,match='Disconnect'): await session.provider_complete('synthetic-return')
    asyncio.run(run())
    assert len(verified)==2


def test_session_change_during_account_get_never_installs(tmp_path):
    session=DesktopSession(tmp_path,start_workers=False)
    async def lookup(*args,**kw):
        session.oauth.generation+=1
        return OWNER
    session.alerts_lookup=lookup
    async def complete(uri):
        return dict(provider='alpaca',purpose='alerts',environment='paper',credential='bearer',account_id=OWNER)
    session.oauth=SimpleNamespace(generation=0,complete=complete,base='https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth',session={'user':{'id':OWNER}})
    async def run():
        with pytest.raises(ValueError,match='session changed'): await session.provider_complete('return')
        assert not session.alerts_credentials.exists()
    asyncio.run(run())


def test_discord_install_respects_outbox_guard(tmp_path):
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        save_secret(session.credentials,json.dumps(dict(account=OWNER,pair={'environment':'paper'})))
        session.provider_destination='intent'
        session.intent_publisher.configure('https://discord.com/api/webhooks/123/original',False)
        with session.intent_publisher.store.connect() as db:
            db.execute("INSERT INTO outbox(id,created,fill,payload,status) VALUES ('uncertain',1,'{}','{}','uncertain')")
        async def complete(uri):
            return dict(provider='discord',environment='paper',credential='https://discord.com/api/webhooks/456/new')
        session.oauth=SimpleNamespace(generation=0,complete=complete,base='https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth',session={'user':{'id':OWNER}})
        with pytest.raises(ValueError,match='queued or uncertain'): await session.provider_complete('return')
        assert session.intent_publisher.destination['webhook'].endswith('/original')
        assert not session.discord_authorized
    asyncio.run(run())

def test_logout_removes_saved_session_without_loading_client(tmp_path):
    session=DesktopSession(tmp_path,start_workers=False)
    saved=tmp_path/'customer-session.secret'
    save_secret(saved,'synthetic-session')
    asyncio.run(session.customer_logout())
    assert not saved.exists()


def test_logout_cancels_registered_oauth_workers_before_forgetting(tmp_path):
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        stopped=[]
        async def wait():
            try: await asyncio.Event().wait()
            finally: stopped.append(True)
        task=asyncio.create_task(wait());await asyncio.sleep(0)
        session.oauth_jobs.add(task)
        async def logout():
            assert stopped
            return {'message':'Signed out.'}
        session.oauth=SimpleNamespace(invalidate=lambda:None,logout=logout)
        await session.customer_logout()
        assert task.cancelled()
    asyncio.run(run())

def test_mocked_login_return_install_and_saved_bearer_recovery(tmp_path,monkeypatch):
    import httpx
    from crier.provider_client import ProviderClient
    from crier import desktop_runtime as runtime
    base='https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth'
    requests=[]
    def edge(request):
        requests.append(request)
        route=request.url.path.rsplit('/',1)[-1]
        if route=='login': return httpx.Response(200,json=dict(access_token='jwt',refresh_token='refresh',expires_in=3600,token_type='bearer',user={'id':OWNER}))
        if route=='capabilities': return httpx.Response(200,json=dict(version=1,service_url=base,auth_project_url=base.split('/functions/')[0],providers=['alpaca']))
        if route=='begin': return httpx.Response(200,json=dict(flow='x'*43,expires_at=200,launch_url=base+'/oauth/browser?ticket='+'t'*43))
        if route=='status': return httpx.Response(200,json={'stage':'ready'})
        if route=='redeem': return httpx.Response(200,json=dict(provider='alpaca',environment='paper',purpose='alerts',account_id=OWNER,credential='provider-bearer',guild_id='',channel_id='',scopes=[]))
        pytest.fail('Unexpected request')
    provider_calls=[]
    def alpaca(request):
        provider_calls.append(request)
        assert request.method=='GET' and request.url.host=='paper-api.alpaca.markets'
        assert request.headers['authorization']=='Bearer provider-bearer'
        assert 'APCA-API-KEY-ID' not in request.headers and 'APCA-API-SECRET-KEY' not in request.headers
        if request.url.path=='/v2/account': return httpx.Response(200,json={'id':OWNER})
        assert request.url.path=='/v2/account/activities/FILL'
        return httpx.Response(200,json=[])
    sync_client,async_client=httpx.Client,httpx.AsyncClient
    monkeypatch.setattr(runtime.httpx,'Client',lambda **kw:sync_client(transport=httpx.MockTransport(alpaca),**kw))
    monkeypatch.setattr(runtime.httpx,'AsyncClient',lambda **kw:async_client(transport=httpx.MockTransport(alpaca),**kw))
    async def run():
        async with async_client(transport=httpx.MockTransport(edge)) as http:
            session=DesktopSession(tmp_path,start_workers=False)
            session.oauth=ProviderClient(base,tmp_path/'customer-session.secret',client=http,clock=lambda:100)
            await session.customer_login('customer@example.test','password')
            await session.provider_begin('alpaca','alerts','paper')
            await session.provider_complete('sentinelcrier://oauth/complete?flow='+'x'*43)
            assert session.broker is None and not session.discord_authorized
            await session.connect_alerts('paper','','')
            assert session.mode=='alerts' and session.device is None
            await session.customer_logout()
            assert session.broker is None and not (tmp_path/'customer-session.secret').exists()
            assert session.alerts_credentials.exists()
    asyncio.run(run())
    assert len(requests)==5 and len(provider_calls)>=4

@pytest.mark.parametrize('provenance',[None,{'service_url':'https://'+'b'*20+'.supabase.co/functions/v1/crier-oauth','owner':OWNER},{'service_url':'https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth','owner':'22345678-1234-1234-1234-123456789abc'}])
def test_bearer_reconnect_rejects_missing_or_other_customer_project(tmp_path,provenance):
    async def run():
        async def no_network(*a,**kw): pytest.fail('Provenance must reject before network')
        session=DesktopSession(tmp_path,start_workers=False,alerts_lookup=no_network)
        session.oauth=SimpleNamespace(base='https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth',session={'user':{'id':OWNER}})
        row=dict(environment='paper',account=OWNER,key='',secret='',bearer='provider')
        if provenance is not None: row['oauth']=provenance
        save_secret(session.alerts_credentials,json.dumps(row))
        with pytest.raises(ValueError,match='OAuth customer'):
            await session.connect_alerts('paper','','')
    asyncio.run(run())


def test_manual_broker_recovery_quarantines_logged_out_oauth_destination(tmp_path):
    import httpx
    async def run():
        async def lookup(*args,**kwargs): return OWNER
        session=DesktopSession(tmp_path,start_workers=False,alerts_lookup=lookup,
            alerts_factory=lambda *a,**k:SimpleNamespace(close=lambda:None))
        async def poll(): pass
        session.poll_alerts=poll
        base='https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth'
        session.oauth=SimpleNamespace(base=base,session=None)
        await session.connect_alerts('paper','manual-key','manual-secret')
        session.publisher.configure('https://discord.com/api/webhooks/123/token',False,
            oauth={'service_url':base,'owner':OWNER})
        with session.publisher.store.connect() as db:
            db.execute("INSERT INTO outbox(id,created,fill,payload,status) VALUES ('retained',1,'{}','{}','uncertain')")
        await session.disconnect()
        await session.connect_alerts('paper','','')
        assert session.broker is not None
        with pytest.raises(ValueError,match='sign-in required'): await session.discord_test()
        with pytest.raises(ValueError,match='sign-in required'): await session.discord_configure('',True)
        session.discord_authorized=True
        def no_network(request): pytest.fail('Quarantined destination must never send')
        with httpx.Client(transport=httpx.MockTransport(no_network)) as http:
            assert not session.deliver_alerts(http)
        with session.publisher.store.connect() as db:
            assert db.execute("SELECT status FROM outbox WHERE id='retained'").fetchone()[0]=='uncertain'
        assert session.publisher.destination['oauth']['owner']==OWNER
        await session.disconnect()
    asyncio.run(run())


def test_customer_session_is_bound_to_exact_service(tmp_path):
    import httpx
    from crier.provider_client import ProviderClient
    a='https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth'
    b=a.replace('a'*20,'b'*20)
    def reply(request):
        return httpx.Response(200,json=dict(access_token='jwt',refresh_token='refresh',expires_in=3600,token_type='bearer',user={'id':OWNER}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
            client=ProviderClient(a,tmp_path/'session',client=http)
            await client.login('a@example.test','pw')
            with pytest.raises(ValueError,match='service'):
                ProviderClient(b,tmp_path/'session',client=http)
    asyncio.run(run())

@pytest.mark.parametrize('mode',['missing','other_project','other_owner'])
def test_discord_provenance_rejected_before_enable(tmp_path,mode):
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        base='https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth'
        identity={'service_url':base,'owner':OWNER}
        session.oauth=SimpleNamespace(base=base,session={'user':{'id':OWNER}})
        session.broker=object()
        session.publisher.configure('https://discord.com/api/webhooks/123/token',False)
        original=session.publisher.destination
        original['credential_mode']='oauth'
        if mode!='missing': original['oauth']=dict(identity)
        if mode=='other_project': original['oauth']['service_url']=base.replace('a'*20,'b'*20)
        if mode=='other_owner': original['oauth']['owner']='22345678-1234-1234-1234-123456789abc'
        with pytest.raises(ValueError,match='OAuth customer'): await session.discord_configure('',True)
        assert not session.discord_authorized and not session.publisher.destination['enabled']
    asyncio.run(run())


def test_failed_refresh_holds_lifecycle_before_reconnect(tmp_path):
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        entered,release=asyncio.Event(),asyncio.Event()
        async def refresh():
            entered.set();await release.wait()
            raise ValueError('Refresh uncertain')
        session.oauth=SimpleNamespace(refresh=refresh)
        refreshing=asyncio.create_task(session.customer_refresh())
        await entered.wait()
        assert session.lifecycle.locked()
        # Neither API-key nor OAuth connection can start while session ownership changes.
        connecting=asyncio.create_task(session.connect_alerts('paper','',''))
        await asyncio.sleep(0)
        assert not connecting.done()
        connecting.cancel();release.set()
        with pytest.raises(ValueError,match='uncertain'):await refreshing
        await asyncio.gather(connecting,return_exceptions=True)
    asyncio.run(run())


def test_logout_fences_new_actions_until_existing_workers_finish(tmp_path):
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        waiting,release=asyncio.Event(),asyncio.Event()
        async def drain():
            waiting.set();await release.wait()
        session.disconnect=drain
        saved=tmp_path/'customer-session.secret'
        save_secret(saved,'synthetic')
        logout=asyncio.create_task(session.customer_logout())
        await waiting.wait()
        assert saved.exists() and session.auth_closing
        with pytest.raises(ValueError,match='Disconnect'): await session.connect_alerts('paper','','')
        with pytest.raises(ValueError,match='Connect first'): session.command('enter')
        release.set();await logout
        assert not saved.exists()
    asyncio.run(run())

def test_discord_oauth_metadata_is_atomic_and_survives_reuse(tmp_path,monkeypatch):
    from crier.discord_settings import DiscordPublisher
    from crier.store import Store
    import crier.discord_settings as settings
    publisher=DiscordPublisher(tmp_path,Store(tmp_path/'alerts.sqlite3'))
    identity={'service_url':'https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth','owner':OWNER}
    publisher.configure('https://discord.com/api/webhooks/123/token',False,oauth=identity)
    saved=json.loads(load_secret(publisher.path))
    assert saved['oauth']==identity and saved['credential_mode']=='oauth'
    publisher.configure('',True)
    assert json.loads(load_secret(publisher.path))['oauth']==identity
    before=publisher.path.read_bytes()
    original=publisher.destination.copy()
    def fail(*a,**kw): raise OSError('Synthetic write failure')
    monkeypatch.setattr(settings,'save_secret',fail)
    with pytest.raises(OSError): publisher.configure('https://discord.com/api/webhooks/456/new',False,oauth=identity)
    assert publisher.path.read_bytes()==before and publisher.destination==original
    assert 'oauth' not in publisher.status()

@pytest.mark.parametrize('bad',[{}, {'owner':OWNER},{'service_url':'http://bad','owner':OWNER},{'service_url':'https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth','owner':'not-a-uuid'}])
def test_discord_oauth_provenance_shape_fails_before_write(tmp_path,bad):
    from crier.discord_settings import DiscordPublisher
    from crier.store import Store
    publisher=DiscordPublisher(tmp_path,Store(tmp_path/'alerts.sqlite3'))
    with pytest.raises(ValueError,match='provenance'):
        publisher.configure('https://discord.com/api/webhooks/123/token',False,oauth=bad)
    assert not publisher.path.exists()


def test_manual_replacement_preserves_outbox_guard_and_can_remove_oauth_marker(tmp_path):
    from crier.discord_settings import DiscordPublisher
    from crier.store import Store
    publisher=DiscordPublisher(tmp_path,Store(tmp_path/'alerts.sqlite3'))
    identity={'service_url':'https://'+'a'*20+'.supabase.co/functions/v1/crier-oauth','owner':OWNER}
    publisher.configure('https://discord.com/api/webhooks/123/token',False,oauth=identity)
    with publisher.store.connect() as db:
        db.execute("INSERT INTO outbox(id,created,fill,payload,status) VALUES ('pending',1,'{}','{}','pending')")
    with pytest.raises(ValueError,match='queued or uncertain'):
        publisher.configure('https://discord.com/api/webhooks/456/manual',False)
    assert publisher.destination['oauth']==identity
    with publisher.store.connect() as db: db.execute('DELETE FROM outbox')
    publisher.configure('https://discord.com/api/webhooks/456/manual',False)
    assert 'oauth' not in publisher.destination and 'credential_mode' not in publisher.destination
