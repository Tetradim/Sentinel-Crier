"""Verified broker discovery and strictly read-only fill adapter."""
import json
import httpx
from .intent_broker import HOSTS, alpaca_headers


async def discover_account(environment, key, secret, client=None, *, bearer=''):
    if environment not in HOSTS:
        raise ValueError('Select an environment and enter both Alpaca credentials.')
    owned = client is None
    client = client or httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False)
    try:
        response = await client.get(HOSTS[environment]+'/v2/account', headers=alpaca_headers(key,secret,bearer=bearer), follow_redirects=False)
        response.raise_for_status()
        row = response.json()
        if not row.get('id') or row.get('status') != 'ACTIVE' or row.get('account_blocked') or row.get('trading_blocked'):
            raise ValueError('The selected Alpaca account is unavailable for trading.')
        return row['id']
    except (httpx.HTTPError, json.JSONDecodeError):
        raise ValueError('Cannot verify Alpaca account. Check credentials, environment and connection.') from None
    finally:
        if owned:
            await client.aclose()


async def discover_alerts_account(environment, key, secret, client=None, *, bearer=''):
    """Verify read access; trading permission is irrelevant for fill monitoring."""
    from .alpaca import _identity
    if environment not in HOSTS:
        raise ValueError('Select an environment and enter both Alpaca credentials.')
    owned = client is None
    client = client or httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False)
    try:
        response = await client.get(HOSTS[environment]+'/v2/account', headers=alpaca_headers(key,secret,bearer=bearer), follow_redirects=False)
        response.raise_for_status()
        return _identity(response.json().get('id'))
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise ValueError('Cannot verify Alpaca read access. Check credentials, environment and connection.') from None
    finally:
        if owned:
            await client.aclose()


class AlpacaFillReader:
    """Read-only account adapter: deliberately has no order mutation methods."""
    def __init__(self, environment, key, secret, account, *, bearer=''):
        self.environment, self.account = environment, account
        self.client = httpx.Client(headers=alpaca_headers(key,secret,bearer=bearer),
                                   timeout=15, trust_env=False, follow_redirects=False)

    def verify(self, environment):
        if environment != self.environment:
            raise ValueError('Broker environment mismatch')
        response = self.client.get(HOSTS[environment]+'/v2/account', follow_redirects=False)
        response.raise_for_status()
        if response.json().get('id') != self.account:
            raise ValueError('Broker account mismatch')
        return self.account

    def close(self):
        self.client.close()
