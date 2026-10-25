"""Server-only OAuth adapters. These exchange grants; they never send or trade."""

from dataclasses import dataclass, field
import json
import re
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import httpx


REJECTION_MESSAGE = 'Provider authorization was rejected.'
MAX_RESPONSE_BYTES = 64 * 1024
TIMEOUT_SECONDS = 15
AUTHORIZE_URLS = {
    'alpaca': 'https://app.alpaca.markets/oauth/authorize',
    'discord': 'https://discord.com/oauth2/authorize',
}
TOKEN_URLS = {
    'alpaca': 'https://api.alpaca.markets/oauth/token',
    'discord': 'https://discord.com/api/oauth2/token',
}
ACCOUNT_URLS = {
    'paper': 'https://paper-api.alpaca.markets/v2/account',
    'live': 'https://api.alpaca.markets/v2/account',
}


class ProviderRejected(ValueError):
    """A deliberately redacted exchange or grant-validation failure."""


def _reject():
    raise ProviderRejected(REJECTION_MESSAGE) from None


def _text(value, limit=4096):
    if not isinstance(value, str) or not value or len(value) > limit:
        _reject()
    if any(ord(char) <= 32 or ord(char) >= 127 for char in value):
        _reject()
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


async def _request_json(client, method, url, **kwargs):
    # Stream decompressed bytes so a chunked/compressed body cannot bypass the cap.
    async with client.stream(method, url, timeout=TIMEOUT_SECONDS,
                             follow_redirects=False, auth=None, **kwargs) as response:
        if response.status_code != 200:
            _reject()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                _reject()
            body.extend(chunk)
        value = json.loads(body, object_pairs_hook=_unique_object)
        if not isinstance(value, dict):
            _reject()
        return value


def _scopes(response, expected):
    value = response.get('scope', '')
    if not isinstance(value, str) or len(value) > 1024:
        _reject()
    scopes = value.split()
    if len(scopes) != len(set(scopes)) or set(scopes) != set(expected):
        _reject()
    return sorted(scopes)


def _account_id(value):
    value = _text(value, 36)
    if str(UUID(value)) != value:
        _reject()
    return value


def _snowflake(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', value):
        _reject()
    if int(value) >= 2 ** 64:
        _reject()
    return value


def _webhook(response):
    webhook = response.get('webhook')
    if not isinstance(webhook, dict) or type(webhook.get('type')) is not int or webhook['type'] != 1:
        _reject()
    webhook_id = _snowflake(webhook.get('id'))
    guild_id = _snowflake(webhook.get('guild_id'))
    channel_id = _snowflake(webhook.get('channel_id'))
    token = _text(webhook.get('token'), 256)
    if not re.fullmatch(r'[A-Za-z0-9._-]+', token):
        _reject()
    url = f'https://discord.com/api/webhooks/{webhook_id}/{token}'
    if webhook.get('url') != url:
        _reject()
    return url, guild_id, channel_id


@dataclass(frozen=True)
class OAuthApplication:
    """One registered application with its exact registered HTTPS callback."""

    provider: str
    client_id: str
    client_secret: str = field(repr=False)
    callback: str

    def __post_init__(self):
        try:
            if self.provider not in AUTHORIZE_URLS:
                _reject()
            _text(self.client_id, 256)
            _text(self.client_secret)
            _text(self.callback, 2048)
            parsed = urlsplit(self.callback)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or '?' in self.callback or '#' in self.callback
                    or '\\' in self.callback):
                _reject()
            # Accessing port also rejects malformed and out-of-range ports.
            parsed.port
        except (ValueError, TypeError, AttributeError):
            _reject()

    def _flow(self, purpose, environment):
        if purpose not in ('alerts', 'trade') or environment not in ACCOUNT_URLS:
            _reject()
        if self.provider == 'discord' and purpose != 'alerts':
            _reject()
        if self.provider == 'discord':
            return ['webhook.incoming']
        return ['trading'] if purpose == 'trade' else []

    def authorization_url(self, state, purpose='alerts', environment='paper'):
        expected = self._flow(purpose, environment)
        _text(state, 1024)
        query = dict(response_type='code', client_id=self.client_id,
                     redirect_uri=self.callback, state=state)
        if self.provider == 'alpaca':
            query['env'] = environment
        if expected:
            query['scope'] = ' '.join(expected)
        return AUTHORIZE_URLS[self.provider] + '?' + urlencode(query)

    async def exchange(self, code, purpose, environment, client: httpx.AsyncClient) -> dict:
        """Validate an authorization-code result without persisting or using it."""
        try:
            expected = self._flow(purpose, environment)
            _text(code)
            response = await _request_json(client, 'POST', TOKEN_URLS[self.provider], data={
                'grant_type': 'authorization_code', 'client_id': self.client_id,
                'client_secret': self.client_secret, 'redirect_uri': self.callback, 'code': code,
            }, headers={'Accept': 'application/json'})
            if response.get('error') is not None:
                _reject()
            token_type = response.get('token_type')
            if not isinstance(token_type, str) or token_type.lower() != 'bearer':
                _reject()
            token = _text(response.get('access_token'))
            scopes = _scopes(response, expected)
            account_id = guild_id = channel_id = ''
            if self.provider == 'alpaca':
                identity = await _request_json(client, 'GET', ACCOUNT_URLS[environment],
                    headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
                account_id = _account_id(identity.get('id'))
                if 'account_id' in response and _account_id(response['account_id']) != account_id:
                    _reject()
                credential = token
            else:
                credential, guild_id, channel_id = _webhook(response)
            return dict(provider=self.provider, environment=environment, purpose=purpose,
                        account_id=account_id, credential=credential, guild_id=guild_id,
                        channel_id=channel_id, scopes=scopes)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
            _reject()
