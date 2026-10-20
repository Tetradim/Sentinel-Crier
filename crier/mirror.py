"""Paired, opt-in execution. The receiver owns credentials and authorization.

Each message describes one execution, never a cumulative order quantity.
Write UNKNOWN before POST. A retry only looks up the same client order ID.
"""
from contextlib import contextmanager
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from hashlib import sha256
import json
import secrets
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Literal
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .models import OCC
from .alpaca import HOSTS
from .lock import single_process


class MirrorEvent(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    event_id: str = Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9:_-]+$')
    environment: Literal['paper', 'live']
    symbol: str = Field(pattern=r'^[A-Z][A-Z0-9.\-]{0,31}$')
    side: Literal['buy', 'sell']
    intent: Literal['buy_to_open', 'sell_to_close']
    quantity: int = Field(strict=True, ge=1, le=1000)
    price: Decimal = Field(gt=0, le=100000, allow_inf_nan=False, max_digits=14, decimal_places=8)
    occurred_at: datetime

    @model_validator(mode='after')
    def valid(self):
        if self.occurred_at.tzinfo is None: raise ValueError('Timestamp requires timezone')
        if self.intent != ('buy_to_open' if self.side == 'buy' else 'sell_to_close'):
            raise ValueError('Only long opening buys and closing sells are supported')
        match = OCC.fullmatch(self.symbol)
        if match:
            stamp = match[2]
            date(2000 + int(stamp[:2]), int(stamp[2:4]), int(stamp[4:]))
            if int(match[4]) == 0: raise ValueError('Invalid strike')
        elif len(self.symbol) > 10: raise ValueError('Invalid contract')
        return self

    def order(self, client_id):
        # Never make a buy more expensive or a sell cheaper by rounding.
        tick = Decimal('.01') if self.price >= 1 or OCC.fullmatch(self.symbol) else Decimal('.0001')
        price = self.price.quantize(tick, rounding=ROUND_FLOOR if self.side == 'buy' else ROUND_CEILING)
        if price <= 0: raise ValueError('Price below minimum increment')
        body = dict(symbol=self.symbol, qty=str(self.quantity), side=self.side, type='limit',
                    time_in_force='day', limit_price=str(price), client_order_id=client_id)
        if OCC.fullmatch(self.symbol): body['position_intent'] = self.intent
        return body


class AlpacaMirrorBroker:
    def __init__(self, environment, key, secret, client=None):
        if environment not in HOSTS or not key or not secret: raise ValueError('Configure receiver Alpaca credentials')
        self.environment = environment
        self.client = client or httpx.Client(timeout=15, follow_redirects=False)
        self.headers = {'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret}

    def request(self, method, path, **kwargs):
        response = self.client.request(method, HOSTS[self.environment] + path, headers=self.headers, **kwargs)
        response.raise_for_status()
        return response.json()

    def account(self): return self.request('GET', '/v2/account')
    def lookup(self, client_id):
        try: return self.request('GET', '/v2/orders:by_client_order_id', params={'client_order_id': client_id})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404: return None
            raise
    def submit(self, body): return self.request('POST', '/v2/orders', json=body)
    def validate(self, event):
        if not self.request('GET', '/v2/clock').get('is_open'):
            raise ValueError('Market is closed; do not queue a mirror order overnight')
        if OCC.fullmatch(event.symbol):
            contract = self.request('GET', '/v2/options/contracts/' + event.symbol)
            if (contract.get('symbol') != event.symbol or not contract.get('tradable')
                    or contract.get('status') != 'active' or str(contract.get('size')) != '100'):
                raise ValueError('Contract is not a tradable standard option')
        else:
            asset = self.request('GET', '/v2/assets/' + event.symbol)
            if not asset.get('tradable') or asset.get('class') != 'us_equity' or asset.get('status') != 'active':
                raise ValueError('Stock is not tradable')
        positions = self.request('GET', '/v2/positions')
        position = next((p for p in positions if p.get('symbol') == event.symbol), None)
        if position and Decimal(position['qty']) < 0: raise ValueError('Short positions are unsupported')
        if event.side == 'sell':
            available = Decimal(position.get('qty_available', '0')) if position else Decimal(0)
            if not available.is_finite() or available < event.quantity:
                raise ValueError('Insufficient available holdings')


class Mirror:
    def __init__(self, path, broker):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.broker = broker; self.lock = RLock()
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS pairs(id TEXT PRIMARY KEY, name TEXT, digest TEXT UNIQUE,
                    enabled INTEGER, revoked INTEGER, account TEXT, environment TEXT);
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, pair_id TEXT, digest TEXT,
                    payload TEXT, state TEXT, note TEXT, client_id TEXT, broker_id TEXT, created REAL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=20); db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def pair(self, name):
        if not self.broker: raise ValueError('Receiver broker is not configured')
        if not name.strip() or len(name) > 60: raise ValueError('Name must contain 1–60 characters')
        account = self.broker.account()
        token = secrets.token_urlsafe(32); identity = secrets.token_hex(16)
        with self.db() as db:
            db.execute('INSERT INTO pairs VALUES (?,?,?,0,0,?,?)', (identity, name, sha256(token.encode()).hexdigest(), account['id'], self.broker.environment))
        return dict(id=identity, token=token, environment=self.broker.environment)

    def follow(self, identity, enabled):
        with self.lock, self.db() as db:
            if not db.execute('UPDATE pairs SET enabled=? WHERE id=? AND revoked=0', (int(enabled), identity)).rowcount:
                raise ValueError('Pairing not found')

    def revoke(self, identity):
        with self.lock, self.db() as db:
            db.execute('UPDATE pairs SET revoked=1,enabled=0 WHERE id=?', (identity,))

    def status(self):
        with self.db() as db:
            return {'configured': self.broker is not None,
                    'pairs': [dict(r) for r in db.execute('SELECT id,name,enabled,revoked,environment FROM pairs')],
                    'events': [dict(r) for r in db.execute('SELECT id,pair_id,payload,state,note,created FROM events ORDER BY created DESC LIMIT 100')]}

    def update(self, identity, state, note='', broker_id=None):
        with self.db() as db:
            db.execute('UPDATE events SET state=?,note=?,broker_id=? WHERE id=?', (state, note, broker_id, identity))
        return {'state': state, 'note': note}

    def reconcile(self):
        if not self.broker: return
        with self.lock, single_process(self.path.with_suffix('.execution.lock')):
            account = self.broker.account()
            with self.db() as db:
                rows = db.execute("""SELECT events.*,pairs.account,pairs.environment FROM events
                    JOIN pairs ON pairs.id=events.pair_id WHERE state NOT IN
                    ('skipped','filled','canceled','expired','rejected')""").fetchall()
            for row in rows:
                if row['account'] != account['id'] or row['environment'] != self.broker.environment: continue
                try:
                    order = self.broker.lookup(row['client_id'])
                    if order:
                        event = MirrorEvent.model_validate_json(row['payload'])
                        self.record_order(row['id'], order, event.order(row['client_id']))
                except Exception:
                    continue

    def record_order(self, identity, order, body):
        # A lookup response must describe the order actually sent.
        if (not isinstance(order, dict) or not order.get('id') or not order.get('status')
                or any(str(order.get(k)) != str(body[k]) for k in ('client_order_id', 'symbol', 'side'))
                or Decimal(order.get('qty', 'NaN')) != Decimal(body['qty'])):
            raise ValueError('Broker order identity mismatch')
        return self.update(identity, order['status'], 'Broker reported status; acceptance is not a fill', order['id'])

    def receive(self, token, event):
        with self.lock, single_process(self.path.with_suffix('.execution.lock')):
            return self._receive(token, event)

    def _receive(self, token, event):
        if not self.broker: raise ValueError('Receiver broker is not configured')
        payload = event.model_dump_json(); digest = sha256(payload.encode()).hexdigest()
        with self.db() as db:
            pair = db.execute('SELECT * FROM pairs WHERE digest=? AND revoked=0', (sha256(token.encode()).hexdigest(),)).fetchone()
            if not pair: raise PermissionError('Pairing is invalid or revoked')
            identity = sha256((pair['id'] + ':' + event.event_id).encode()).hexdigest()
            old = db.execute('SELECT * FROM events WHERE id=?', (identity,)).fetchone()
        client_id = 'crier-m-' + identity[:40]
        body = event.order(client_id)
        if old:
            if old['digest'] != digest: raise ValueError('Event ID already used with different contents')
            if old['state'] == 'unknown':
                try:
                    account = self.broker.account()
                    if account['id'] != pair['account'] or self.broker.environment != pair['environment']:
                        return {'state': 'unknown', 'note': 'Receiver account changed'}
                    order = self.broker.lookup(client_id)
                    if order: return self.record_order(identity, order, body)
                except Exception: pass
            return {'state': old['state'], 'note': old['note']}
        age = (datetime.now(timezone.utc) - event.occurred_at).total_seconds()
        if not -5 <= age <= 60: raise ValueError('Fill expired or timestamp is in the future')
        if event.environment != pair['environment'] or self.broker.environment != pair['environment']:
            raise ValueError('Source and receiver environments must match')
        # Persist the delivery even when paused: resume never replays a paused trade.
        with self.db() as db:
            unresolved = db.execute("SELECT 1 FROM events WHERE state='unknown'").fetchone()
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)',
                       (identity, pair['id'], digest, payload, 'skipped', '', client_id, None, datetime.now().timestamp()))
        if not pair['enabled']: return self.update(identity, 'skipped', 'Following is paused')
        if unresolved: return self.update(identity, 'skipped', 'Reconcile the unresolved receiver order first')
        try:
            account = self.broker.account()
            if account['id'] != pair['account']: raise ValueError('Receiver account changed; create a new pairing')
            if account.get('status') != 'ACTIVE' or account.get('trading_blocked', True) or account.get('account_blocked', True):
                raise ValueError('Receiver account cannot trade')
            if OCC.fullmatch(event.symbol) and int(account.get('options_trading_level') or 0) < 2:
                raise ValueError('Receiver requires level 2 options permission')
            self.broker.validate(event)
            if (datetime.now(timezone.utc)-event.occurred_at).total_seconds() > 60:
                raise ValueError('Fill expired during broker validation')
        except Exception:
            return self.update(identity, 'skipped', 'Account, contract, market hours or available holdings validation failed')
        self.update(identity, 'unknown', 'Submission pending reconciliation; never automatically resubmit')
        try:
            order = self.broker.submit(body)
            return self.record_order(identity, order, body)
        except Exception:
            # Includes HTTP errors: a conflicting ID or proxy response is not proof of no order.
            return {'state': 'unknown', 'note': 'Submission pending reconciliation; never automatically resubmit'}
