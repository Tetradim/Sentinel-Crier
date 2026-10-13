"""Read-only Tradier order polling; transaction_date is an order-update time."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
import time

import httpx

from .lock import single_process
from .models import Snapshot
from .store import Store

PAGE_SIZE = 1000
MAX_PAGES = 100
HOSTS = {'sandbox': 'https://sandbox.tradier.com', 'production': 'https://api.tradier.com'}


def _identity(value):
    if type(value) not in (str, int) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', str(value)):
        raise ValueError('Missing or invalid order/account identity')
    if type(value) is int and value <= 0:
        raise ValueError('Invalid order identity')
    return str(value)


def _decimal(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('Missing numeric order field')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('Invalid numeric order field') from None
    if not result.is_finite():
        raise ValueError('Invalid numeric order field')
    return result


def normalize(payload, account, environment='sandbox'):
    """Normalize cumulative execution values, never infer an execution timestamp."""
    if not isinstance(payload, dict):
        raise ValueError('Expected an order object')
    if environment not in HOSTS:
        raise ValueError('Unknown Tradier environment')
    account = _identity(account)
    order_id = _identity(payload.get('id'))
    category = payload.get('class')
    if category not in ('equity', 'option') or payload.get('leg') or payload.get('legs') or payload.get('num_legs', 1) != 1:
        raise ValueError('Unsupported complex order')
    if payload.get('type') not in ('market', 'limit', 'stop', 'stop_limit'):
        raise ValueError('Unsupported order type')
    sides = ({'buy': ('BUY', 'UNKNOWN'), 'sell': ('SELL', 'UNKNOWN'),
              'buy_to_cover': ('BUY', 'CLOSE'), 'sell_short': ('SELL', 'OPEN')}
             if category == 'equity' else
             {'buy_to_open': ('BUY', 'OPEN'), 'buy_to_close': ('BUY', 'CLOSE'),
              'sell_to_open': ('SELL', 'OPEN'), 'sell_to_close': ('SELL', 'CLOSE')})
    if payload.get('side') not in sides:
        raise ValueError('Ambiguous order side')
    quantity = _decimal(payload.get('quantity'))
    executed = _decimal(payload.get('exec_quantity'))
    if quantity <= 0 or executed < 0 or executed > quantity:
        raise ValueError('Inconsistent execution quantity')
    status = payload.get('status')
    if status not in ('open', 'pending', 'partially_filled', 'filled', 'canceled', 'expired', 'rejected', 'error'):
        raise ValueError('Unknown order status')
    if status == 'filled' and executed != quantity:
        raise ValueError('Filled order has inconsistent quantity')
    if status == 'partially_filled' and not 0 < executed < quantity:
        raise ValueError('Partial order has inconsistent quantity')
    if executed == 0:
        return None
    if status not in ('partially_filled', 'filled', 'canceled', 'expired'):
        raise ValueError('Execution with ambiguous order status')
    stamp = payload.get('transaction_date')
    if not isinstance(stamp, str):
        raise ValueError('Missing order update timestamp')
    side, intent = sides[payload['side']]
    return Snapshot(broker='tradier', account=account, environment=environment, order_id=order_id,
                    category='US_OPTION' if category == 'option' else 'US_STOCK',
                    symbol=payload.get('option_symbol') if category == 'option' else payload.get('symbol'),
                    side=side, intent=intent, cumulative_qty=executed,
                    average_price=_decimal(payload.get('avg_fill_price')), occurred_at=stamp,
                    time_basis='order_updated', status='FILLED' if executed == quantity else 'PARTIAL')


def _orders(body):
    if not isinstance(body, dict) or 'orders' not in body:
        raise ValueError('Missing orders envelope')
    envelope = body['orders']
    if envelope is None or envelope == 'null':
        return []
    if not isinstance(envelope, dict) or 'order' not in envelope:
        raise ValueError('Malformed orders envelope')
    rows = envelope['order']
    if rows is None or rows == 'null':
        return []
    if isinstance(rows, dict):
        return [rows]
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError('Malformed order list')
    return rows


def _fetch(client, account, environment):
    if environment not in HOSTS:
        raise ValueError('Unknown Tradier environment')
    account = _identity(account)
    url = f'{HOSTS[environment]}/v1/accounts/{account}/orders'
    rows, identities = [], set()
    for page in range(1, MAX_PAGES + 1):
        response = client.get(url, params={'limit': PAGE_SIZE, 'page': page},
                              headers={'Accept': 'application/json'}, follow_redirects=False)
        response.raise_for_status()
        batch = _orders(response.json())
        if len(batch) > PAGE_SIZE:
            raise ValueError('Unexpected pagination size')
        for row in batch:
            identity = _identity(row.get('id'))
            if identity in identities:
                raise ValueError('Overlapping or repeated order pages; retry complete poll')
            identities.add(identity)
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
    raise ValueError('Order pagination limit exceeded; baseline remains incomplete')


def _checkpoint_key(account, environment):
    scope = json.dumps(['tradier', environment, account])
    return 'tradier_baseline:' + hashlib.sha256(scope.encode()).hexdigest()


def _checkpoint(store, key):
    with store.connect() as db:
        row = db.execute('SELECT value FROM config WHERE id=?', (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _finish_baseline(store, key, checkpoint, settings):
    # A saved, immutable batch permits retry after interruption without suppressing
    # fills that arrived after the first complete response.
    for data in checkpoint['snapshots']:
        result = store.ingest(Snapshot.model_validate(data), settings, baseline=True)
        if result['outcome'] not in ('baseline', 'duplicate'):
            raise ValueError('Baseline conflicts with existing order state; reconcile manually')
    with store.connect() as db:
        db.execute('UPDATE config SET value=? WHERE id=?',
                   (json.dumps({'state': 'ready', 'captured_at': checkpoint['captured_at']}), key))


def poll_once(store, client, account, environment='sandbox', verified=False):
    """Fetch all pages before writes. Caller must serialize polls for this store."""
    rows = _fetch(client, account, environment)
    evidence = {'environment': environment, 'account': account, 'orders': rows}
    if not verified:
        # Preserve private evidence even when this adapter cannot interpret it.
        store.audit('tradier_observed', evidence)
    snapshots, invalid = [], 0
    for row in rows:
        try:
            snap = normalize(row, account, environment)
            if snap is not None:
                snapshots.append(snap)
        except (ValueError, KeyError, TypeError):
            invalid += 1
    if invalid:
        if verified:
            store.audit('tradier_observed', evidence)
        store.audit('invalid', {'reason': 'Unsupported or incomplete Tradier orders; inspect private capture',
                                'invalid_orders': invalid})
    if not verified:
        return {'state': 'capture_only', 'orders': len(rows), 'fills': len(snapshots),
                'invalid_orders': invalid}
    # Reject the whole verified poll before any watermarks, including first baseline.
    if invalid:
        raise ValueError('Unsupported or incomplete Tradier order batch')
    key = _checkpoint_key(account, environment)
    settings = store.get_settings()
    checkpoint = _checkpoint(store, key)
    first = checkpoint is None
    if first:
        checkpoint = {'state': 'pending', 'captured_at': time.time(),
                      'snapshots': [snap.model_dump(mode='json') for snap in snapshots]}
        with store.connect() as db:
            db.execute('INSERT INTO config(id,value) VALUES (?,?)', (key, json.dumps(checkpoint)))
    if checkpoint['state'] == 'pending':
        _finish_baseline(store, key, checkpoint, settings)
    if not first:
        for snap in snapshots:
            store.ingest(snap, settings)
    return {'state': 'observing', 'orders': len(rows), 'fills': len(snapshots)}


def observe(config):
    with single_process(config.data_dir / "observer.lock"):
        _observe(config)


def _observe(config):
    token = os.getenv('TRADIER_ACCESS_TOKEN', '')
    account = os.getenv('TRADIER_ACCOUNT_ID', '')
    environment = os.getenv('TRADIER_ENV', 'sandbox')
    if not token or not account:
        raise ValueError('Set TRADIER_ACCESS_TOKEN and TRADIER_ACCOUNT_ID on the server')
    _identity(account)
    if environment not in HOSTS:
        raise ValueError('TRADIER_ENV must be sandbox or production')
    verified = os.getenv('CRIER_TRADIER_VERIFIED', 'false').lower() == 'true'
    store = Store(config.data_dir / 'crier.sqlite3')
    def state(value):
        with store.connect() as db:
            db.execute("INSERT OR REPLACE INTO config VALUES ('observer',?)",
                       (json.dumps({'broker': 'tradier', 'state': value, 'updated': time.time(),
                                    'verified': verified, 'environment': environment}),))
    state('connecting')
    with httpx.Client(headers={'Authorization': f'Bearer {token}'}, timeout=20,
                      follow_redirects=False, trust_env=False) as client:
        while True:
            try:
                result = poll_once(store, client, account, environment, verified)
                state(result['state'])
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                # No credential, account URL, or raw response in console messages.
                state('error')
                store.audit('invalid', {'reason': 'Tradier poll failed; retry uses persisted progress. Inspect private audit records.'})
            time.sleep(10)
