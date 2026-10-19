"""Official read-only Alpaca FILL activity monitor (paper by default).

First complete history fetch enrolls silently. Activity IDs, cumulative cost,
Store watermarks/outbox and cursor commit together; a failed batch changes none.
This module never submits or cancels orders. Open/close intent is UNKNOWN because
account activities supply buy/sell, not reliable position intent.
"""
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import os
import time

import httpx

from .lock import single_process
from .models import OCC, Snapshot
from .store import Store

HOSTS = {'paper': 'https://paper-api.alpaca.markets', 'live': 'https://api.alpaca.markets'}
PAGE_SIZE = 100
MAX_PAGES = 1000


def _identity(value):
    if not isinstance(value, str) or not value or len(value) > 100 or any(ord(c) < 32 for c in value):
        raise ValueError('Missing or invalid Alpaca identity')
    return value


def _decimal(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError('Invalid Alpaca number')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError('Invalid Alpaca number') from None
    if (not number.is_finite() or number.adjusted() > 19
            or number.as_tuple().exponent < -20 or len(number.as_tuple().digits) > 40):
        raise ValueError('Invalid Alpaca number')
    return number


def _fetch(client, environment, cursor):
    rows, seen = [], set()
    for _ in range(MAX_PAGES):
        params = {'direction': 'asc', 'page_size': PAGE_SIZE}
        if cursor:
            params['page_token'] = cursor
        response = client.get(HOSTS[environment] + '/v2/account/activities/FILL',
                              params=params, follow_redirects=False)
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list) or len(batch) > PAGE_SIZE:
            raise ValueError('Malformed Alpaca activity page')
        for row in batch:
            if not isinstance(row, dict):
                raise ValueError('Malformed Alpaca activity')
            identity = _identity(row.get('id'))
            if identity in seen:
                raise ValueError('Repeated Alpaca activity page')
            seen.add(identity)
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        next_cursor = batch[-1]['id']
        if next_cursor == cursor:
            raise ValueError('Alpaca pagination made no progress')
        cursor = next_cursor
    raise ValueError('Alpaca history exceeds page limit; enrollment incomplete')


def normalize(row, account, environment, previous=None):
    """Accumulate execution cost using decimals; never treat fill price as average."""
    if environment not in HOSTS:
        raise ValueError('ALPACA_ENV must be paper or live')
    if row.get('activity_type') != 'FILL' or row.get('type') not in ('fill', 'partial_fill'):
        raise ValueError('Unsupported Alpaca activity')
    if row.get('side') not in ('buy', 'sell'):
        raise ValueError('Unsupported Alpaca side')
    _identity(row.get('id'))
    order_id = _identity(row.get('order_id'))
    qty, cumulative, leaves, price = [_decimal(row.get(k)) for k in ('qty', 'cum_qty', 'leaves_qty', 'price')]
    if qty <= 0 or price <= 0 or leaves < 0:
        raise ValueError('Invalid Alpaca execution')
    old_qty = Decimal(previous['qty']) if previous else Decimal(0)
    old_cost = Decimal(previous['cost']) if previous else Decimal(0)
    if cumulative != old_qty + qty:
        raise ValueError('Incomplete or inconsistent Alpaca fill history')
    symbol = row.get('symbol')
    if not isinstance(symbol, str):
        raise ValueError('Missing Alpaca symbol')
    identity = [symbol, row['side']]
    if previous and previous['identity'] != identity:
        raise ValueError('Alpaca order identity changed')
    with localcontext() as context:
        context.prec = 50
        cost = old_cost + qty * price
        average = (cost / cumulative).quantize(Decimal('0.00000001'))
    snap = Snapshot(broker='alpaca', environment='sandbox' if environment == 'paper' else 'production',
                    account=account, order_id=order_id, symbol=symbol,
                    category='US_OPTION' if OCC.fullmatch(symbol) else 'US_STOCK',
                    side=row['side'].upper(), intent='UNKNOWN', cumulative_qty=cumulative,
                    average_price=average,
                    occurred_at=row.get('transaction_time'), status='FILLED' if leaves == 0 else 'PARTIAL')
    return snap, {'qty': str(cumulative), 'cost': str(cost), 'identity': identity}


def poll_once(store, client, account, environment='paper'):
    if environment not in HOSTS:
        raise ValueError('ALPACA_ENV must be paper or live')
    _identity(account)
    scope = hashlib.sha256(json.dumps([environment, account]).encode()).hexdigest()
    key = 'alpaca_cursor:' + scope
    with store.connect() as db:
        saved = db.execute('SELECT value FROM config WHERE id=?', (key,)).fetchone()
    checkpoint = json.loads(saved[0]) if saved else None
    rows = _fetch(client, environment, checkpoint['cursor'] if checkpoint else None)
    settings = store.get_settings()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT value FROM config WHERE id=?', (key,)).fetchone()
        if (current[0] if current else None) != (saved[0] if saved else None):
            raise ValueError('Concurrent Alpaca poll; retry')
        db.execute('CREATE TABLE IF NOT EXISTS alpaca_activities (scope TEXT, id TEXT, digest TEXT, PRIMARY KEY(scope,id))')
        db.execute('CREATE TABLE IF NOT EXISTS alpaca_totals (scope TEXT, id TEXT, data TEXT, PRIMARY KEY(scope,id))')
        cursor = checkpoint['cursor'] if checkpoint else None
        accepted = 0
        for row in rows:
            identity = _identity(row.get('id'))
            digest = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            seen = db.execute('SELECT digest FROM alpaca_activities WHERE scope=? AND id=?', (scope, identity)).fetchone()
            if seen:
                if seen[0] != digest:
                    raise ValueError('Alpaca execution changed; reconcile activity')
                continue
            order_id = _identity(row.get('order_id'))
            old = db.execute('SELECT data FROM alpaca_totals WHERE scope=? AND id=?', (scope, order_id)).fetchone()
            snap, total = normalize(row, account, environment, json.loads(old[0]) if old else None)
            result = store.ingest_in_transaction(db, snap, settings, baseline=checkpoint is None, execution_price=_decimal(row['price']))
            if result['outcome'] not in ('baseline', 'queued', 'duplicate', 'review', 'reconciled'):
                raise ValueError('Alpaca Store state conflicts with activity')
            db.execute('INSERT OR REPLACE INTO alpaca_totals VALUES (?,?,?)', (scope, order_id, json.dumps(total)))
            db.execute('INSERT INTO alpaca_activities VALUES (?,?,?)', (scope, identity, digest))
            cursor = identity
            accepted += 1
        db.execute('INSERT OR REPLACE INTO config VALUES (?,?)', (key, json.dumps({'cursor': cursor})))
    return {'state': 'observing', 'activities': len(rows), 'fills': accepted, 'enrolled': checkpoint is None}


def observe(config):
    with single_process(config.data_dir / 'observer.lock'):
        _observe(config)


def _observe(config):
    environment = os.getenv('ALPACA_ENV', 'paper').lower()
    key, secret = os.getenv('APCA_API_KEY_ID', ''), os.getenv('APCA_API_SECRET_KEY', '')
    if environment not in HOSTS or not key or not secret:
        raise ValueError('Set APCA_API_KEY_ID and APCA_API_SECRET_KEY; ALPACA_ENV must be paper or live')
    store = Store(config.data_dir / 'crier.sqlite3')
    def state(value):
        with store.connect() as db:
            db.execute("INSERT OR REPLACE INTO config VALUES ('observer',?)", (json.dumps({
                'broker': 'alpaca', 'state': value, 'environment': environment,
                'verified': True, 'updated': time.time()}),))
    state('connecting')
    with httpx.Client(headers={'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret,
                              'Accept': 'application/json'}, timeout=20,
                      follow_redirects=False, trust_env=False) as client:
        while True:
            try:
                response = client.get(HOSTS[environment] + '/v2/account', follow_redirects=False)
                response.raise_for_status()
                account = _identity(response.json().get('id'))
                result = poll_once(store, client, account, environment)
                state(result['state'])
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                state('error')
                store.audit('invalid', {'reason': 'Alpaca poll failed; persisted cursor retained. Check credentials, activity support and connectivity.'})
            time.sleep(10)
