import asyncio
import hashlib
from urllib.parse import urlsplit, parse_qs

import httpx
import pytest

pytest.importorskip('cryptography', minversion='50')
from fastapi.testclient import TestClient
from crier.oauth_flows import FlowStore
from crier.oauth_gateway import create_oauth_app, SupabaseOwnerVerifier
from crier.oauth_providers import OAuthApplication

ORIGIN = 'https://oauth.example'
PROOF = 'd' * 43
ACCOUNT = '12345678-1234-1234-1234-123456789abc'


def app(tmp_path):
    store = FlowStore(tmp_path/'flows.sqlite3', b'k' * 32)
    applications = {p: OAuthApplication(p, 'client', 'secret', ORIGIN+'/oauth/callback/'+p) for p in ('alpaca', 'discord')}
    async def owner(header):
        if header not in ('Bearer owner-a', 'Bearer owner-b'):
            raise ValueError('private auth error')
        return header.removeprefix('Bearer ')
    async def browser_owner(request):
        identity = request.cookies.get('browser-owner')
        if identity not in ('owner-a','owner-b'):
            raise ValueError('Login required')
        return identity
    requests = []
    def provider(request):
        requests.append(request)
        if request.url.path == '/oauth/token':
            return httpx.Response(200, json={'access_token':'provider-secret', 'token_type':'Bearer', 'scope':''})
        assert request.url.path == '/v2/account' and request.method == 'GET'
        return httpx.Response(200, json={'id':ACCOUNT})
    gateway = create_oauth_app(store=store, applications=applications, authenticate=owner, public_origin=ORIGIN,
        authenticate_browser=browser_owner,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(provider)))
    return gateway, store, requests


def begin(client, provider='alpaca'):
    client.cookies.set('browser-owner', 'owner-a')
    response = client.post('/oauth/begin', headers={'Authorization':'Bearer owner-a'}, json={
        'provider':provider, 'purpose':'alerts', 'environment':'paper',
        'challenge':hashlib.sha256(PROOF.encode()).hexdigest()})
    assert response.status_code == 200, response.text
    body = response.json()
    browser = client.get(body['launch_url'], follow_redirects=False)
    assert browser.status_code == 303
    state = parse_qs(urlsplit(browser.headers['location']).query)['state'][0]
    return body['flow'], state


def test_full_authenticated_cookie_bound_exchange_and_one_use_redemption(tmp_path):
    gateway, store, calls = app(tmp_path)
    with TestClient(gateway, base_url=ORIGIN) as client:
        flow, state = begin(client)
        assert any(key.startswith('__Host-crier-oauth-') for key in client.cookies)
        callback = client.get('/oauth/callback/alpaca', params={'state':state, 'code':'authorization-code'}, follow_redirects=False)
        assert callback.status_code == 303
        assert callback.headers['location'] == 'sentinelcrier://oauth/complete?flow='+flow
        assert 'secret' not in str(callback.headers) and 'authorization-code' not in str(callback.headers)
        assert callback.headers['cache-control'] == 'no-store'
        assert len(calls) == 2
        payload = {'flow':flow,'proof':PROOF}
        wrong = client.post('/oauth/redeem', json=payload, headers={'Authorization':'Bearer owner-b'})
        assert wrong.status_code == 400
        result = client.post('/oauth/redeem', json=payload, headers={'Authorization':'Bearer owner-a'})
        assert result.json()['credential'] == 'provider-secret'
        assert client.post('/oauth/redeem', json=payload, headers={'Authorization':'Bearer owner-a'}).status_code == 400
        assert store.status('owner-a', flow)['stage'] == 'redeemed'


def test_foreign_browser_duplicate_query_and_wrong_issuer_do_not_exchange(tmp_path):
    gateway, store, calls = app(tmp_path)
    with TestClient(gateway, base_url=ORIGIN) as client:
        flow, state = begin(client)
        with TestClient(gateway, base_url=ORIGIN) as other:
            other.cookies.set('browser-owner','owner-a')
            assert other.get('/oauth/callback/alpaca', params={'state':state,'code':'secret'}).status_code == 400
        assert client.get('/oauth/callback/alpaca?state='+state+'&state='+state+'&code=secret').status_code == 400
        assert client.get('/oauth/callback/alpaca', params={'state':state,'code':'secret','iss':'https://discord.com'}).status_code == 400
        assert not calls
        assert store.status('owner-a', flow)['stage'] == 'launched'
        denied_flow, denied_state = begin(client, 'discord')
        assert client.get('/oauth/callback/discord', params={'state':denied_state,'error':'access_denied'}).status_code == 400
        denial = client.get('/oauth/callback/discord', params={'state':denied_state,'error':'access_denied','iss':'https://discord.com'}, follow_redirects=False)
        assert denial.status_code == 303
        assert store.status('owner-a', denied_flow)['stage'] == 'failed'
        assert not calls


def test_errors_are_private_and_factory_rejects_missing_auth_or_wrong_callback(tmp_path):
    gateway, store, calls = app(tmp_path)
    with TestClient(gateway, base_url=ORIGIN) as client:
        response = client.post('/oauth/redeem', json={'flow':'sensitive-value', 'proof':'private-proof'})
        assert response.status_code in (400,401)
        assert 'private-proof' not in response.text and 'sensitive-value' not in response.text
        body = client.post('/oauth/begin', headers={'Authorization':'Bearer owner-a'}, content=b'x'*9000)
        assert body.status_code == 413 and body.headers['cache-control'] == 'no-store'
    with pytest.raises(ValueError):
        create_oauth_app(store=store, applications={}, authenticate=None, public_origin=ORIGIN)
    bad = OAuthApplication('alpaca','client','secret','https://different.example/oauth/callback/alpaca')
    with pytest.raises(ValueError):
        create_oauth_app(store=store, applications={'alpaca':bad}, authenticate=lambda _:None, authenticate_browser=lambda _:None, public_origin=ORIGIN)


def test_shared_launch_url_cannot_link_victim_browser_to_attackers_owner(tmp_path):
    gateway, store, calls = app(tmp_path)
    with TestClient(gateway, base_url=ORIGIN) as client:
        result = client.post('/oauth/begin', headers={'Authorization':'Bearer owner-a'}, json={
            'provider':'alpaca','purpose':'alerts','environment':'paper','challenge':hashlib.sha256(PROOF.encode()).hexdigest()}).json()
        client.cookies.set('browser-owner','owner-b')
        assert client.get(result['launch_url'], follow_redirects=False).status_code == 400
        assert store.status('owner-a', result['flow'])['stage'] == 'pending'
        client.cookies.set('browser-owner','owner-a')
        launched = client.get(result['launch_url'], follow_redirects=False)
        state = parse_qs(urlsplit(launched.headers['location']).query)['state'][0]
        client.cookies.set('browser-owner','owner-b')
        assert client.get('/oauth/callback/alpaca', params={'state':state,'code':'code'}).status_code == 400
        assert store.status('owner-a', result['flow'])['stage'] == 'launched'
        assert not calls


def test_exchange_uncertainty_stays_claimed_and_late_cancelled_result_cannot_return_credentials(tmp_path, monkeypatch):
    gateway, store, calls = app(tmp_path)
    with TestClient(gateway, base_url=ORIGIN) as client:
        flow, state = begin(client)
        async def timeout(*args, **kwargs):
            raise httpx.ReadTimeout('provider-token-must-not-leak')
        monkeypatch.setattr(OAuthApplication, 'exchange', timeout)
        result = client.get('/oauth/callback/alpaca', params={'state':state,'code':'one-use-code'}, follow_redirects=False)
        assert result.status_code == 303
        assert 'provider-token' not in result.text
        assert store.status('owner-a', flow)['stage'] == 'exchanging'
        assert client.get('/oauth/callback/alpaca', params={'state':state,'code':'one-use-code'}, follow_redirects=False).status_code == 400
        next_flow, next_state = begin(client)
        async def cancelled(*args, **kwargs):
            store.cancel('owner-a', next_flow, PROOF)
            return {'credential':'discarded-late-token'}
        monkeypatch.setattr(OAuthApplication, 'exchange', cancelled)
        late = client.get('/oauth/callback/alpaca', params={'state':next_state,'code':'code'}, follow_redirects=False)
        assert late.status_code == 303
        assert store.status('owner-a', next_flow)['stage'] == 'cancelled'
        assert client.post('/oauth/redeem', json={'flow':next_flow,'proof':PROOF}, headers={'Authorization':'Bearer owner-a'}).status_code == 400


def test_supabase_verifier_checks_server_user_not_editable_metadata():
    async def run():
        calls=[]
        def respond(request):
            calls.append(request)
            return httpx.Response(200,json={'id':ACCOUNT,'is_anonymous':False,'user_metadata':{'owner':'attacker'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            verifier=SupabaseOwnerVerifier('https://abcdefghijklmnopqrst.supabase.co','public-key',client=client)
            assert await verifier('Bearer opaque-user-session') == ACCOUNT
            assert calls[0].url.path == '/auth/v1/user'
            assert calls[0].headers['apikey'] == 'public-key'
            with pytest.raises(ValueError): await verifier('Bearer token\nsecret')
        for value in ({'id':ACCOUNT,'is_anonymous':True},{'id':'not-an-identity','is_anonymous':False}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=value))) as client:
                verifier=SupabaseOwnerVerifier('https://abcdefghijklmnopqrst.supabase.co','public-key',client=client)
                with pytest.raises(ValueError): await verifier('Bearer opaque-user-session')
    asyncio.run(run())
