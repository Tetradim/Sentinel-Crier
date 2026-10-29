"""Durable route identity and isolated Windows sessions (Alpaca execution only)."""
import asyncio
import inspect
import json
import re
from .device_secrets import load_secret
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4

from .desktop_runtime import DesktopSession
from .error_log import ErrorLog, emit_event


class DesktopConnections:
    def __init__(self, folder, session_factory=DesktopSession):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.factory = session_factory
        self.guard = threading.RLock()
        self.operations = asyncio.Lock()
        self.sessions = {}
        self.stopping = False
        with self.database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS routes (id TEXT PRIMARY KEY, label TEXT NOT NULL, legacy INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS ownership (broker TEXT NOT NULL, environment TEXT NOT NULL, account TEXT NOT NULL, route TEXT NOT NULL, PRIMARY KEY(broker,environment,account))')
            db.execute('CREATE TABLE IF NOT EXISTS selection (singleton INTEGER PRIMARY KEY CHECK(singleton=1), route TEXT NOT NULL)')
            if not db.execute('SELECT 1 FROM routes').fetchone():
                identity = uuid4().hex
                db.execute('INSERT INTO routes VALUES (?, ?, 1)', (identity, 'Original connection'))
                db.execute('INSERT INTO selection VALUES (1, ?)', (identity,))
            self.selected = db.execute('SELECT route FROM selection WHERE singleton=1').fetchone()[0]
        routes = self.routes()
        if sum(route['legacy'] == 1 for route in routes) != 1 or any(route['legacy'] not in (0, 1) for route in routes):
            raise ValueError('Invalid legacy connection registry.')
        if any(not isinstance(route['label'], str) or not 1 <= len(route['label'].strip()) <= 80 for route in routes):
            raise ValueError('Invalid connection name in registry.')
        with self.database() as db:
            if db.execute('SELECT 1 FROM ownership WHERE route NOT IN (SELECT id FROM routes)').fetchone():
                raise ValueError('Account ownership references missing connection evidence.')
        if len(routes) > 16 or self.selected not in {route['id'] for route in routes}:
            raise ValueError('Invalid connection registry; restore its private recovery backup.')
        for route in routes:
            if not re.fullmatch(r'[0-9a-f]{32}', route['id']):
                raise ValueError('Invalid connection identity.')
            session = self._session(route)
            # Preserve original protected credentials and journals in place.
            for path in (session.credentials, session.alerts_credentials):
                if path.exists():
                    saved = json.loads(load_secret(path))
                    environment = saved.get('environment') or saved.get('pair', {}).get('environment')
                    self.claim(route['id'], environment, saved['account'])
            self.import_journal_claims(route['id'], session.folder)

    def database(self):
        return sqlite3.connect(self.folder / 'connections.sqlite3')

    def routes(self):
        with self.database() as db:
            return [dict(id=row[0], label=row[1], legacy=row[2])
                    for row in db.execute('SELECT id,label,legacy FROM routes ORDER BY rowid')]

    def _session(self, route):
        identity = route['id']
        if identity not in self.sessions:
            folder = self.folder if route['legacy'] else self.folder / 'connections' / identity
            if not route['legacy'] and folder.resolve() != self.folder.resolve() / 'connections' / identity:
                raise ValueError('Connection directory redirects outside its private route.')
            session = self.factory(folder, error_log=ErrorLog(folder / 'logs'))
            for name in ('account_lookup', 'alerts_lookup'):
                lookup = getattr(session, name)
                credentials = session.credentials if name == 'account_lookup' else session.alerts_credentials
                async def checked(environment, *args, _lookup=lookup, _credentials=credentials,
                                  _trading=name == "account_lookup", **kwargs):
                    account = await _lookup(environment, *args, **kwargs)
                    if _credentials.exists():
                        saved = json.loads(load_secret(_credentials))
                        saved_environment = saved.get('environment') or saved.get('pair', {}).get('environment')
                        if (saved_environment, saved['account']) != (environment, account):
                            raise ValueError('This route is pinned to its original account and environment. Add a separate connection.')
                    retained = self.import_journal_claims(identity, session.folder)
                    if _trading and any(env == environment and old != account for env, old in retained):
                        raise ValueError("This route has retained execution history for another account. Recover it in the original route; add a separate connection for a new account.")
                    self.claim(identity, environment, account)
                    return account
                setattr(session, name, checked)
            self.sessions[identity] = session
            emit_event(session.error_log, "desktop.connection_loaded")
        return self.sessions[identity]

    def import_journal_claims(self, identity, folder):
        # Engine journals retain ownership even if protected credentials were lost.
        # Open read-only: migration must never create, rewrite or recover a journal.
        bindings = set()
        for path in (folder / 'journal').glob('intent-*.sqlite3'):
            if path.name == 'intent-device.sqlite3': continue
            try:
                with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
                    rows = db.execute('SELECT id,environment,account FROM intent_pin').fetchall()
                if len(rows) > 1 or (rows and rows[0][0] != 1):
                    raise ValueError('Conflicting retained journal account evidence.')
                if rows:
                    self.claim(identity, rows[0][1], rows[0][2])
                    bindings.add((rows[0][1], rows[0][2]))
            except sqlite3.Error as exc:
                raise ValueError('Cannot verify retained journal account ownership; restore its private recovery backup.') from exc
        return bindings

    def claim(self, identity, environment, account):
        if environment not in ('paper', 'live') or not isinstance(account, str) or not account:
            raise ValueError('Cannot establish broker account ownership.')
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            owner = db.execute('SELECT route FROM ownership WHERE broker=? AND environment=? AND account=?',
                               ('alpaca', environment, account)).fetchone()
            if owner and owner[0] != identity:
                raise ValueError('This Alpaca account and environment belongs to another route. Its journal must be retained.')
            db.execute('INSERT OR IGNORE INTO ownership VALUES (?, ?, ?, ?)', ('alpaca', environment, account, identity))

    @property
    def session(self):
        with self.guard:
            return self.sessions[self.selected]

    def add(self, label):
        label = str(label).strip()
        if not label or len(label) > 80:
            raise ValueError('Enter a connection name of 1Ã¢â‚¬â€œ80 characters.')
        with self.guard:
            if self.stopping:
                raise ValueError('Connections are shutting down.')
            if len(self.sessions) >= 16:
                raise ValueError('Maximum 16 connections. Existing journals must be retained.')
            identity = uuid4().hex
            route = dict(id=identity, label=label, legacy=False)
            self._session(route)
            with self.database() as db:
                db.execute('INSERT INTO routes VALUES (?, ?, 0)', (identity, label))
            self.select(identity)
            return identity

    def select(self, identity):
        with self.guard:
            if identity not in self.sessions:
                raise ValueError('Unknown connection.')
            with self.database() as db:
                db.execute('UPDATE selection SET route=? WHERE singleton=1', (identity,))
            self.selected = identity

    async def invoke(self, identity, method, *args, **kwargs):
        if method in ('disconnect_all', 'shutdown'):
            async with self.operations:
                if method == 'shutdown': self.stopping = True
                results = await asyncio.gather(*(self._invoke(session, 'shutdown' if method == 'shutdown' else 'disconnect')
                                                for session in self.sessions.values()), return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException): raise result
            return
        # Serialize account verification through broker installation across every route.
        # The lookup check therefore cannot race another route's connect.
        if method in ('connect', 'connect_alerts', 'provider_complete'):
            async with self.operations:
                if self.stopping: raise ValueError('Connections are shutting down.')
                return await self._invoke(self.sessions[identity], method, *args, **kwargs)
        if self.stopping: raise ValueError('Connections are shutting down.')
        return await self._invoke(self.sessions[identity], method, *args, **kwargs)

    async def _invoke(self, session, method, *args, **kwargs):
        tracked = method.startswith('provider_') or method in ('customer_login', 'customer_refresh')
        task = asyncio.current_task()
        if tracked: session.oauth_jobs.add(task)
        try:
            value = getattr(session, method)(*args, **kwargs)
            return await value if inspect.isawaitable(value) else value
        finally:
            if tracked: session.oauth_jobs.discard(task)
