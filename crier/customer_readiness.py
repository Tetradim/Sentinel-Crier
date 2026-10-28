"""Customer-facing summaries and observational, read-only connection probes.

Probe results contain fixed codes only. They never establish delivery or grant
execution permission, and do not update device cursors or cached dashboards.
"""
import asyncio
import json
import threading
import time

import httpx

from .copy_dashboard import PresenceReport, StatusReport, stamp, validate_status_binding
from .diagnostic_protocol import DiagnosticObservation
from .intent_protocol import IntentEvent
from .service_url import service_url
from .alpaca import _identity
from .intent_broker import HOSTS, alpaca_headers
from .updates import _DeadlineIO

MAX_RESPONSE = 256 * 1024
MAX_ACCOUNT_RESPONSE = 128 * 1024
ACCOUNT_TIMEOUT = 10


def connection_summary(state):
    """Describe evidence from DesktopSession.status without exposing identities."""
    execution = state.get('execution') or {}
    health = state.get('health') or []
    orders = execution.get('orders') or []
    unresolved = any(order.get('status') in ('unknown', 'cancel_unknown', 'submit_unknown', 'reconcile_required') for order in orders)
    blocked = execution.get('blocked') or execution.get('state') in ('blocked', 'reconcile_required', 'waiting_for_reconciliation')
    blocked = blocked or any(row.get('component') == 'execution' and row.get('state') == 'blocked' for row in health)
    if unresolved or blocked:
        return dict(title='Needs reconciliation', detail='Existing orders need broker confirmation before new entries.',
                    action='Inspect broker orders and reconnect the same account and pairing.')
    if not state.get('connected'):
        return dict(title='Disconnected', detail='Monitoring and trade sharing are stopped.', action='Connect a saved account or complete setup.')
    if state.get('mode') == 'alerts':
        alert_state = (state.get('alerts') or {}).get('state')
        unhealthy = state.get('health_error') or any(row.get('component') in ('broker', 'fills') and row.get('state') != 'healthy' for row in health)
        title = 'Connecting' if alert_state == 'connecting' else 'Reconnecting' if unhealthy or alert_state not in ('observing', 'running') else 'Monitoring alerts'
        return dict(title=title, detail='Read-only fill monitoring; no orders are submitted.', action='Check fill monitoring and Discord delivery status.')
    pair = state.get('pair') or {}
    role = pair.get('role')
    if role not in ('host', 'follower'):
        return dict(title='Connecting', detail='Account connected; a trade pairing is required.', action='Configure a Host or Follower pairing.')
    component = 'relay_send' if role == 'host' else 'relay_receive'
    transport = state.get('transport')
    def acceptable(row):
        return row.get('state') == 'healthy' or (
            row.get('component') == 'relay_send' and row.get('state') == 'idle'
            and row.get('reason') == 'no_work')
    relevant = [row for row in health if row.get('component') in ('broker', component)]
    missing = not all(any(row.get('component') == name for row in relevant) for name in ('broker', component))
    unhealthy = (state.get('health_error') or any(not acceptable(row) for row in relevant)
                 or (missing and transport in ('push', 'poll')))
    if unhealthy or transport not in ('push', 'poll'):
        title = 'Reconnecting' if unhealthy or transport in ('reconnecting', 'degraded') else 'Connecting'
        return dict(title=title, detail='Trade sharing is waiting for a healthy relay connection.', action='Check the connection and saved pairing; delivery is not confirmed.')
    enabled = (execution.get('settings') or {}).get('enabled') is True
    return dict(title='Hosting' if role == 'host' else 'Following',
                detail='Relay connected. ' + ('New entries enabled.' if enabled else 'New entries paused; existing orders still require monitoring.'),
                action='Inspect broker orders and device-reported copy status.')


def _text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise ValueError('Invalid dashboard identity')


def _dashboard(data, pair):
    fields = {'version', 'channel_id', 'environment', 'role', 'actor', 'generated_at', 'members', 'events', 'statuses', 'diagnostics', 'truncated'}
    if not isinstance(data, dict) or set(data) != fields or type(data['version']) is not int or data['version'] != 1:
        raise ValueError('Invalid dashboard schema')
    if data['environment'] != pair['environment'] or data['role'] != pair['role'] or type(data['truncated']) is not bool:
        raise ValueError('Dashboard binding mismatch')
    _text(data['channel_id']); _text(data['actor']); stamp(data['generated_at'])
    if (data['role'] == 'host') != (data['actor'] == 'host'):
        raise ValueError('Dashboard actor mismatch')
    for key, limit in (('members', 200), ('events', 50), ('statuses', 200), ('diagnostics', 200)):
        if not isinstance(data[key], list) or len(data[key]) > limit:
            raise ValueError('Invalid dashboard list')
    for member in data['members']:
        if not isinstance(member, dict) or set(member) != {'actor', 'role', 'revoked', 'presence', 'last_seen_at'}:
            raise ValueError('Invalid member')
        _text(member['actor'])
        if member['role'] not in ('host', 'follower') or type(member['revoked']) is not bool:
            raise ValueError('Invalid member role')
        if member['presence'] is not None: PresenceReport.model_validate(member['presence'])
        if member['last_seen_at'] is not None: stamp(member['last_seen_at'])
    events = {}
    for value in data['events']:
        event = IntentEvent.model_validate(value)
        if event.environment != pair['environment']: raise ValueError('Event environment mismatch')
        events[event.event_id] = event.to_dict()
    for row in data['statuses']:
        if not isinstance(row, dict) or set(row) != {'actor', 'report', 'received_at'}:
            raise ValueError('Invalid status')
        _text(row['actor']); stamp(row['received_at'])
        report = StatusReport.model_validate(row['report'])
        validate_status_binding(report, events[report.event_id])
    for row in data['diagnostics']:
        if not isinstance(row, dict) or set(row) != {'actor', 'event_id', 'observation'} or row['event_id'] not in events:
            raise ValueError('Invalid diagnostic')
        _text(row['actor']); DiagnosticObservation.model_validate(row['observation'])


async def _relay_probe(pair, environment, client):
    if not isinstance(pair, dict) or set(pair) != {'url', 'token', 'environment', 'role'}:
        raise ValueError('Invalid pairing')
    if pair['environment'] != environment or pair['role'] not in ('host', 'follower'):
        raise ValueError('Pairing binding mismatch')
    token = pair['token']
    if not isinstance(token, str) or not 32 <= len(token) <= 256 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('Invalid pairing credential')
    url = service_url(pair['url'], allow_local=True) + '/api/sync/dashboard'
    async with client.stream('GET', url, headers={'Authorization': 'Bearer ' + token}, follow_redirects=False, timeout=10) as response:
        if response.status_code != 200:
            return 'authentication_failed' if response.status_code in (401, 403) else 'relay_unavailable'
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_RESPONSE: raise ValueError('Oversized dashboard')
        _dashboard(json.loads(body), pair)
    return 'relay_verified'


def _bounded_account(broker, environment, account, cancelled, *, require_trading=True):
    """Own an account-only client whose DNS, headers and body share a deadline."""
    _identity(account)
    source = getattr(broker, 'client', None)
    if environment not in HOSTS or getattr(broker, 'environment', None) != environment or not isinstance(source, httpx.Client):
        raise ValueError('Unsupported account adapter')
    auth = source.headers
    bearer = auth.get('Authorization', '')
    key, secret = auth.get('APCA-API-KEY-ID', ''), auth.get('APCA-API-SECRET-KEY', '')
    if bearer:
        if not bearer.startswith('Bearer '): raise ValueError('Invalid account authentication')
        headers = alpaca_headers(key, secret, bearer=bearer[7:])
    else:
        headers = alpaca_headers(key, secret)
    headers.update({'Accept':'application/json', 'Accept-Encoding':'identity'})
    deadline = time.monotonic() + ACCOUNT_TIMEOUT
    def active():
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise ValueError('Account probe cancelled or timed out')
    active()
    transport = httpx.HTTPTransport(trust_env=False, retries=0)
    pool = getattr(transport, '_pool', None)
    backend = getattr(pool, '_network_backend', None)
    if backend is None or not callable(getattr(backend, 'connect_tcp', None)):
        transport.close()
        raise ValueError('Account deadline transport unavailable')
    pool._network_backend = _DeadlineIO(backend, deadline, cancelled)
    try:
        with httpx.Client(transport=transport, trust_env=False, follow_redirects=False, headers=headers) as client:
            active()
            with client.stream('GET', HOSTS[environment] + '/v2/account', follow_redirects=False,
                               timeout=httpx.Timeout(ACCOUNT_TIMEOUT, connect=min(5, ACCOUNT_TIMEOUT))) as response:
                active()
                if response.status_code != 200 or response.headers.get('Content-Encoding', 'identity') != 'identity':
                    raise ValueError('Account read failed')
                body = bytearray()
                chunks = iter((response.content,)) if response.is_stream_consumed else response.iter_raw()
                for chunk in chunks:
                    active()
                    body.extend(chunk)
                    if len(body) > MAX_ACCOUNT_RESPONSE: raise ValueError('Account response too large')
                active()
                row = json.loads(body)
                if not isinstance(row, dict) or _identity(row.get('id')) != account:
                    raise ValueError('Account identity mismatch')
                if require_trading and (row.get('status') != 'ACTIVE' or any(
                        type(row.get(flag)) is not bool or row[flag] for flag in ('trading_blocked', 'account_blocked'))):
                    raise ValueError('Account unavailable for trading')
                return account
    finally:
        transport.close()


async def probe_connection(broker, environment, account, pair=None, *, client=None,
                           require_trading=True, account_reader=None):
    """Read account identity and dashboard; never submit a test order or report."""
    rows = []
    try:
        if environment not in ('paper', 'live') or not isinstance(account, str) or not account.strip():
            raise ValueError('Invalid account binding')
        _identity(account)
        if getattr(broker, 'environment', environment) != environment:
            raise ValueError('Broker environment mismatch')
        cancelled = threading.Event()
        reader = asyncio.create_task(asyncio.to_thread(account_reader or _bounded_account,
                    broker, environment, account, cancelled, require_trading=require_trading))
        try:
            verified = await asyncio.shield(reader)
        except asyncio.CancelledError:
            cancelled.set()
            while not reader.done():
                try: await asyncio.shield(reader)
                except asyncio.CancelledError: continue
                except Exception: break
            # Retrieve any worker exception before propagating cancellation.
            await asyncio.gather(reader, return_exceptions=True)
            raise
        if not isinstance(verified, str) or verified != account:
            raise ValueError('Broker identity mismatch')
        rows.append(dict(component='broker', status='passed', code='account_verified'))
    except Exception:
        rows.append(dict(component='broker', status='failed', code='account_verification_failed'))
    if pair is None:
        rows.append(dict(component='relay', status='not_configured', code='pairing_not_configured'))
    else:
        owned = client is None
        client = client or httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False)
        try:
            code = await asyncio.wait_for(_relay_probe(pair, environment, client), timeout=10)
        except (TimeoutError, httpx.TimeoutException):
            code = 'relay_timeout'
        except Exception:
            code = 'relay_verification_failed'
        finally:
            if owned: await client.aclose()
        rows.append(dict(component='relay', status='passed' if code == 'relay_verified' else 'failed', code=code))
    return dict(ready=all(row['status'] in ('passed', 'not_configured') for row in rows), rows=rows, delivery='not_tested')
