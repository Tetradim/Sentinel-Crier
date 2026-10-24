import json
import httpx
import pytest
from crier.store import Store
from crier.models import Settings
from crier.discord_settings import DiscordPublisher

URL='https://discord.com/api/webhooks/123/private-token'

def test_destination_is_protected_and_change_keeps_jobs(tmp_path):
    store=Store(tmp_path/'alerts.sqlite3')
    publisher=DiscordPublisher(tmp_path,store)
    publisher.configure(URL,True)
    result=publisher.test_message(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(429,json={'retry_after':3}))))
    assert result['status']=='pending'
    assert result['attempts']==1
    assert 'private-token' not in json.dumps(publisher.status())
    assert b'private-token' not in (tmp_path/'discord-destination.secret').read_bytes()
    with pytest.raises(ValueError,match='queued'):
        publisher.configure('https://discord.com/api/webhooks/456/other',True)
    reloaded=DiscordPublisher(tmp_path,Store(tmp_path/'alerts.sqlite3'))
    assert reloaded.status()['history'][0]['status']=='pending'
    assert reloaded.status()['settings']['format']==Settings().format

def test_sample_is_labelled_and_uncertain_delivery_not_blindly_retried(tmp_path):
    publisher=DiscordPublisher(tmp_path,Store(tmp_path/'alerts.sqlite3'))
    publisher.configure(URL,False)
    requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        raise httpx.ReadTimeout('lost response')
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result=publisher.test_message(client)
        assert result['status']=='uncertain'
        assert 'TEST' in requests[0]['content']
        assert requests[0]['allowed_mentions']=={'parse':[]}
        assert not publisher.deliver(client)
    assert len(requests)==1

def test_old_presentation_settings_migrate_with_defaults(tmp_path):
    store=Store(tmp_path/'alerts.sqlite3')
    with store.connect() as db:
        db.execute("INSERT INTO config VALUES ('settings',?)",(json.dumps({'format':'card','show_quantity':False}),))
    publisher=DiscordPublisher(tmp_path,store)
    assert publisher.status()['settings']['show_time'] is True
    payload=publisher.preview('option_buy')
    assert payload['embeds']
    assert 'Broker-reported' in payload['embeds'][0]['footer']['text']

def test_desktop_reads_authoritative_fills_without_replaying_history(tmp_path):
    from crier.desktop_runtime import DesktopSession
    from crier.intent_broker import AlpacaIntentBroker
    from crier.alpaca import HOSTS
    async def account(*args): return 'account-one'
    activities=[]
    def respond(request):
        if request.url.path=='/v2/account': return httpx.Response(200,json={'id':'account-one','status':'ACTIVE'})
        assert request.url.path=='/v2/account/activities/FILL'
        after=request.url.params.get('page_token')
        rows=activities[activities.index(next(r for r in activities if r['id']==after))+1:] if after else activities
        return httpx.Response(200,json=rows)
    def factory(environment,key,secret,identity):
        return AlpacaIntentBroker(environment,key,secret,identity,httpx.Client(transport=httpx.MockTransport(respond)))
    async def run():
        session=DesktopSession(tmp_path,account_lookup=account,broker_factory=factory,start_workers=False)
        await session.connect(json.dumps(dict(url='https://relay.example',token='t'*40,environment='paper',role='host')),'key','secret')
        activities.append(dict(id='a1',activity_type='FILL',type='partial_fill',order_id='order1',symbol='SPY261218C00600000',side='buy',qty='1',cum_qty='1',leaves_qty='1',price='0.201',transaction_time='2026-10-23T14:00:00Z'))
        await session.poll_alerts()
        await session.poll_alerts()
        assert len(session.publisher.store.history())==1
        job=session.publisher.store.history()[0]
        assert job['fill']['price']=='0.201'
        assert job['fill']['verification']=='broker_reported'
        assert job['fill']['status']=='PARTIAL'
        await session.disconnect()
        await session.connect('','rotated-key','rotated-secret')
        await session.poll_alerts()
        assert len(session.publisher.store.history())==1
        assert session.status()['alerts']['state']=='observing'
        await session.disconnect()
    import asyncio
    asyncio.run(run())

def test_explicit_retry_only_allows_definitively_failed_jobs(tmp_path):
    publisher=DiscordPublisher(tmp_path,Store(tmp_path/'alerts.sqlite3'))
    publisher.configure(URL,False)
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(400,json={}))) as client:
        failed=publisher.test_message(client)
    assert publisher.retry(failed['id'])['status']=='pending'
    with publisher.store.connect() as db:
        db.execute("UPDATE outbox SET status='uncertain' WHERE id=?",(failed['id'],))
    with pytest.raises(ValueError,match='uncertain'):
        publisher.retry(failed['id'])

def test_browser_discord_controls_authorized_and_redact_destination(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from crier.app import create_app
    from crier.config import Config
    from crier import app as module
    original=httpx.Client
    def fake(**kwargs):
        return original(transport=httpx.MockTransport(lambda r:httpx.Response(403,json={})),**kwargs)
    monkeypatch.setattr(module.httpx,'Client',fake)
    app=create_app(Config(data_dir=tmp_path,token='a'*32))
    headers={'Authorization':'Bearer '+'a'*32}
    with TestClient(app) as client:
        assert client.get('/api/discord').status_code==401
        assert client.put('/api/discord',json={'webhook':URL,'enabled':True}).status_code==401
        response=client.put('/api/discord',headers=headers,json={'webhook':URL,'enabled':False})
        assert response.status_code==200
        assert 'private-token' not in response.text
        job=client.post('/api/discord/test',headers=headers,json={}).json()
        assert job['status']=='failed'
        assert client.post('/api/discord/'+job['id']+'/retry',headers=headers,json={}).json()['status']=='pending'
        assert client.post('/api/discord/'+job['id']+'/close',json={}).status_code==401
        assert client.post('/api/discord/'+job['id']+'/close',headers=headers,json={}).json()['status']=='closed'
        assert client.get('/api/status',headers=headers).json()['discord_configured']

def test_explicit_close_preserves_evidence_and_releases_destination(tmp_path):
    publisher=DiscordPublisher(tmp_path,Store(tmp_path/'alerts.sqlite3'))
    publisher.configure(URL,False)
    def timeout(request): raise httpx.ReadTimeout('ambiguous')
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        uncertain=publisher.test_message(client)
    closed=publisher.close(uncertain['id'])
    assert closed['status']=='closed'
    assert closed['payload']==uncertain['payload']
    assert closed['attempts']==uncertain['attempts']
    assert closed['fill']==uncertain['fill']
    assert 'no resend' in closed['note'].lower()
    publisher.configure('https://discord.com/api/webhooks/456/new-destination',False)
    assert len(publisher.store.history())==1
    with pytest.raises(ValueError): publisher.retry(uncertain['id'])
    for state in ['sending','sent']:
        with publisher.store.connect() as db:
            db.execute('UPDATE outbox SET status=? WHERE id=?',(state,uncertain['id']))
        with pytest.raises(ValueError,match='pending, failed, uncertain or review'):
            publisher.close(uncertain['id'])

def test_failed_job_blocks_destination_change_until_closed(tmp_path):
    publisher=DiscordPublisher(tmp_path,Store(tmp_path/'alerts.sqlite3'))
    publisher.configure(URL,False)
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(401))) as client:
        failed=publisher.test_message(client)
    assert failed['status']=='failed'
    with pytest.raises(ValueError):
        publisher.configure('https://discord.com/api/webhooks/456/new-destination',False)
    publisher.close(failed['id'])
    publisher.configure('https://discord.com/api/webhooks/456/new-destination',False)


def test_explicit_initial_alert_destination_accepts_only_never_attempted_jobs(tmp_path):
    store = Store(tmp_path/'alerts.sqlite3')
    publisher = DiscordPublisher(tmp_path, store)
    with store.connect() as db:
        db.execute("INSERT INTO outbox(id,created,fill,payload) VALUES ('first',0,'{}','{}')")
    with pytest.raises(ValueError, match='queued'):
        publisher.configure(URL, False)
    result = publisher.configure(URL, False, allow_initial=True)
    assert result['configured'] and not result['enabled']
    assert result['history'][0]['status'] == 'pending'
    assert result['history'][0]['attempts'] == 0
    with pytest.raises(ValueError, match='queued'):
        publisher.configure('https://discord.com/api/webhooks/456/other', True, allow_initial=True)


@pytest.mark.parametrize('status,attempts', [('pending',1), ('sending',1), ('uncertain',1), ('sent',1), ('closed',0), ('failed',0), ('review',0)])
def test_initial_destination_never_retargets_prior_delivery_evidence(tmp_path, status, attempts):
    store = Store(tmp_path/'alerts.sqlite3')
    publisher = DiscordPublisher(tmp_path, store)
    with store.connect() as db:
        db.execute("INSERT INTO outbox(id,created,fill,payload,status,attempts) VALUES ('old',0,'{}','{}',?,?)", (status,attempts))
    with pytest.raises(ValueError, match='destination'):
        publisher.configure(URL, True, allow_initial=True)
    assert not publisher.destination['enabled']


def test_lost_destination_secret_cannot_retarget_unattempted_queue(tmp_path):
    store = Store(tmp_path/'alerts.sqlite3')
    publisher = DiscordPublisher(tmp_path, store)
    publisher.configure(URL, False)
    with store.connect() as db:
        db.execute("INSERT INTO outbox(id,created,fill,payload) VALUES ('old',0,'{}','{}')")
    publisher.path.unlink()
    reloaded = DiscordPublisher(tmp_path, store)
    with pytest.raises(ValueError, match='destination'):
        reloaded.configure('https://discord.com/api/webhooks/456/other',True,allow_initial=True)


def test_failed_destination_save_keeps_memory_disabled(tmp_path, monkeypatch):
    import crier.discord_settings as module
    publisher = DiscordPublisher(tmp_path, Store(tmp_path/'alerts.sqlite3'))
    monkeypatch.setattr(module, 'save_secret', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        publisher.configure(URL, True, allow_initial=True)
    assert publisher.destination == {'webhook':'','enabled':False}
