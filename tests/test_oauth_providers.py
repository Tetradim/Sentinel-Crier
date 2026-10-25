import asyncio
from dataclasses import FrozenInstanceError
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from crier.oauth_providers import OAuthApplication, ProviderRejected, REJECTION_MESSAGE


CALLBACK = 'https://connections.example/oauth/callback'
ACCOUNT = '7f9fbbe8-1610-4ab5-9ccb-9fa97341be17'
TOKEN = 'synthetic-secret-token'
WEBHOOK_TOKEN = 'synthetic-webhook-token'
WEBHOOK_URL = f'https://discord.com/api/webhooks/123456789012345678/{WEBHOOK_TOKEN}'


def app(provider='alpaca', callback=CALLBACK):
    return OAuthApplication(provider, 'application-id', 'application-secret', callback)


def exchange(application, responses, purpose='alerts', environment='paper'):
    requests = []

    def handle(request):
        requests.append(request)
        value = responses[len(requests) - 1]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, httpx.Response):
            return value
        return httpx.Response(200, json=value)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
            return await application.exchange('synthetic-code', purpose, environment, client)

    return asyncio.run(run()), requests


def alpaca_token(**changes):
    return dict(access_token=TOKEN, token_type='Bearer', scope='') | changes


def discord_token(**changes):
    return dict(access_token=TOKEN, token_type='Bearer', scope='webhook.incoming', webhook=dict(
        type=1, id='123456789012345678', guild_id='223456789012345678',
        channel_id='323456789012345678', token=WEBHOOK_TOKEN, url=WEBHOOK_URL,
    )) | changes


def test_configuration_is_frozen_and_secret_is_hidden():
    application = app()
    assert 'application-secret' not in repr(application)
    with pytest.raises(FrozenInstanceError):
        application.provider = 'discord'


@pytest.mark.parametrize('callback', [
    'http://connections.example/oauth/callback', 'https://user:password@connections.example/cb',
    'https://connections.example/cb?next=secret', 'https://connections.example/cb#fragment',
    'https://connections.example/cb?', 'https://connections.example/cb#',
    ' https://connections.example/cb', 'https://connections.example/\ncb', 'https:///cb',
])
def test_callback_requires_exact_https_registration(callback):
    with pytest.raises(ValueError):
        app(callback=callback)


@pytest.mark.parametrize('provider,purpose,scope,host', [
    ('alpaca', 'alerts', None, 'app.alpaca.markets'),
    ('alpaca', 'trade', ['trading'], 'app.alpaca.markets'),
    ('discord', 'alerts', ['webhook.incoming'], 'discord.com'),
])
def test_authorization_pins_hosts_and_minimum_scopes(provider, purpose, scope, host):
    parsed = urlsplit(app(provider).authorization_url('state-proof', purpose, 'live'))
    query = parse_qs(parsed.query)
    assert parsed.scheme == 'https' and parsed.hostname == host
    assert query['redirect_uri'] == [CALLBACK]
    assert query['state'] == ['state-proof']
    assert query['response_type'] == ['code']
    assert query.get('scope') == scope
    if provider == 'alpaca':
        assert query['env'] == ['live']
    assert 'application-secret' not in parsed.query


@pytest.mark.parametrize('provider,purpose,environment', [
    ('webull', 'alerts', 'paper'), ('alpaca', 'admin', 'paper'),
    ('alpaca', 'alerts', 'sandbox'), ('discord', 'trade', 'paper'),
])
def test_unsupported_flows_fail_before_network(provider, purpose, environment):
    with pytest.raises(ValueError):
        app(provider).authorization_url('state', purpose, environment)


@pytest.mark.parametrize('environment,host', [('paper', 'paper-api.alpaca.markets'), ('live', 'api.alpaca.markets')])
def test_alpaca_grant_verifies_account_on_selected_host(environment, host):
    grant, requests = exchange(app(), [alpaca_token(), {'id': ACCOUNT}], environment=environment)
    assert grant == dict(provider='alpaca', environment=environment, purpose='alerts',
                         account_id=ACCOUNT, credential=TOKEN, guild_id='', channel_id='', scopes=[])
    assert str(requests[0].url) == 'https://api.alpaca.markets/oauth/token'
    assert requests[0].method == 'POST'
    form = parse_qs(requests[0].content.decode())
    assert form == dict(grant_type=['authorization_code'], code=['synthetic-code'],
                        client_id=['application-id'], client_secret=['application-secret'], redirect_uri=[CALLBACK])
    assert str(requests[1].url) == f'https://{host}/v2/account'
    assert requests[1].headers['Authorization'] == f'Bearer {TOKEN}'
    assert requests[1].method == 'GET'
    assert all(request.extensions['timeout']['read'] == 15 for request in requests)


def test_alpaca_trade_is_explicit():
    grant, _ = exchange(app(), [alpaca_token(scope='trading'), {'id': ACCOUNT}], purpose='trade')
    assert grant['purpose'] == 'trade' and grant['scopes'] == ['trading']


def test_discord_webhook_grant_has_no_extra_requests():
    grant, requests = exchange(app('discord'), [discord_token()])
    assert grant == dict(provider='discord', environment='paper', purpose='alerts', account_id='',
                         credential=WEBHOOK_URL, guild_id='223456789012345678',
                         channel_id='323456789012345678', scopes=['webhook.incoming'])
    assert len(requests) == 1
    assert str(requests[0].url) == 'https://discord.com/api/oauth2/token'
    assert requests[0].method == 'POST'


@pytest.mark.parametrize('token', [
    alpaca_token(scope='trading'), alpaca_token(scope='account:write'),
    alpaca_token(token_type='Basic'), alpaca_token(access_token=''),
    alpaca_token(access_token='secret\r\ninjection'), alpaca_token(scope=['trading']),
    {'error': 'provider-secret'}, [],
])
def test_alpaca_rejects_escalation_and_malformed_tokens(token):
    with pytest.raises(ProviderRejected, match=f'^{REJECTION_MESSAGE}$'):
        exchange(app(), [token])


@pytest.mark.parametrize('identity', [{'id': 'not-a-uuid'}, {'id': ACCOUNT.upper()}, {}, {'id': None}])
def test_alpaca_requires_canonical_account_uuid(identity):
    with pytest.raises(ProviderRejected):
        exchange(app(), [alpaca_token(), identity])


def test_alpaca_rejects_account_mismatch():
    with pytest.raises(ProviderRejected):
        exchange(app(), [alpaca_token(account_id='87bababc-d55b-424b-88d4-ff4c534dc9b2'), {'id': ACCOUNT}])


@pytest.mark.parametrize('changes', [
    {'type': 2}, {'type': True}, {'id': '../escape'}, {'guild_id': None},
    {'channel_id': '0'}, {'token': 'secret?query'}, {'url': 'https://evil.example/webhook'},
    {'url': WEBHOOK_URL + '?wait=true'}, {'url': WEBHOOK_URL.replace('123456789012345678', '123')},
])
def test_discord_rejects_untrusted_webhook_identity(changes):
    response = discord_token()
    response['webhook'].update(changes)
    with pytest.raises(ProviderRejected):
        exchange(app('discord'), [response])


@pytest.mark.parametrize('changes', [{'scope': 'webhook.incoming identify'}, {'scope': ''}, {'token_type': 'Basic'}, {'webhook': None}])
def test_discord_rejects_unexpected_grants(changes):
    with pytest.raises(ProviderRejected):
        exchange(app('discord'), [discord_token(**changes)])


@pytest.mark.parametrize('response', [
    httpx.Response(302, headers={'Location': 'https://evil.example/secret'}),
    httpx.Response(400, text='provider-secret'),
    httpx.Response(200, content=b'x' * (65536 + 1)),
    httpx.Response(200, content=b'{invalid secret'),
    httpx.ConnectError('provider-secret'),
])
def test_exchange_failures_are_generic_and_never_follow_redirects(response):
    with pytest.raises(ProviderRejected) as error:
        exchange(app(), [response])
    assert str(error.value) == REJECTION_MESSAGE
    assert error.value.__suppress_context__
    assert error.value.__cause__ is None


def test_deeply_nested_json_is_a_generic_rejection():
    response = httpx.Response(200, content=b'[' * 2000 + b'0' + b']' * 2000)
    with pytest.raises(ProviderRejected, match=f'^{REJECTION_MESSAGE}$'):
        exchange(app(), [response])


def test_duplicate_json_keys_cannot_hide_escalation():
    response = httpx.Response(200, content=(
        b'{"access_token":"synthetic","token_type":"Bearer","scope":"trading","scope":""}'
    ))
    with pytest.raises(ProviderRejected):
        exchange(app(), [response])


@pytest.mark.parametrize('scope', ['', 'trading account:write', 'trading trading'])
def test_trade_requires_exact_trading_grant(scope):
    with pytest.raises(ProviderRejected):
        exchange(app(), [alpaca_token(scope=scope)], purpose='trade')


def test_missing_alpaca_scope_is_default_readonly():
    token = alpaca_token()
    del token['scope']
    grant, _ = exchange(app(), [token, {'id': ACCOUNT}])
    assert grant['scopes'] == []


def test_chunked_response_is_bounded_independently_of_content_length():
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(17):
                yield b'x' * 4096

    response = httpx.Response(200, headers={'Content-Length': '1'}, stream=Chunks())
    with pytest.raises(ProviderRejected):
        exchange(app(), [response])


def test_invalid_exchange_flow_never_requests_a_token():
    with pytest.raises(ProviderRejected):
        exchange(app('discord'), [], purpose='trade')
