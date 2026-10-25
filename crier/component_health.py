"""Informational, scoped observations; never authorizes execution or delivery."""
from contextlib import closing
from pathlib import Path
import sqlite3
import threading
import time
from uuid import uuid4

COMPONENTS = {
    'broker': ('Broker account', 60, 'Reconnect the same account to verify access.'),
    'fills': ('Fill monitoring', 45, 'Reconnect Alerts; the saved cursor and history remain.'),
    'relay_send': ('Trade sharing', 60, 'Inspect queued instructions and the saved connection.'),
    'relay_receive': ('Trade receiving', 60, 'Inspect the saved connection; expired entries are not replayed.'),
    'execution': ('Execution worker', 15, 'Inspect broker orders and refresh reconciliation.'),
    'discord': ('Discord delivery', 60, 'Inspect delivery history before retrying uncertain messages.'),
}
REASONS = frozenset(('verified','checked','delivered','no_work','connection_failed',
    'authentication_failed','rejected','uncertain','rate_limited','invalid_events',
    'reconciliation_required','customer_required','waiting_retry'))


def emit(observer, component, state, reason):
    # Diagnostics may fail independently; never interrupt a durable broker/send outcome.
    if observer:
        try: observer(component,state,reason)
        except Exception: pass


class ComponentHealth:
    def __init__(self, path, *, wall=time.time, monotonic=time.monotonic):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.wall,self.monotonic=wall,monotonic
        self.lock=threading.RLock()
        with closing(self._db()) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS component_health (
                scope TEXT, component TEXT, state TEXT, reason TEXT, checked REAL,
                last_success REAL, session TEXT, PRIMARY KEY(scope,component))''')
            db.execute('CREATE TABLE IF NOT EXISTS health_context (id INTEGER PRIMARY KEY CHECK(id=1),scope TEXT NOT NULL)')
        self.begin_session()

    def _db(self):
        # Diagnostics are expendable; never wait behind an external SQLite writer.
        db=sqlite3.connect(self.path,timeout=0,isolation_level=None)
        db.row_factory=sqlite3.Row
        return db

    def begin_session(self):
        with self.lock:
            self.session=uuid4().hex
            self.origin=(self.wall(),self.monotonic())
            self.samples={}
            self.successes={}

    def latest_scope(self):
        with self.lock, closing(self._db()) as db:
            row=db.execute('SELECT scope FROM health_context WHERE id=1').fetchone()
            return row[0] if row else 'unconfigured'

    def record(self, scope, component, state, reason):
        if component not in COMPONENTS or state not in ('healthy','degraded','blocked','idle') or reason not in REASONS:
            raise ValueError('Invalid component health observation')
        with self.lock:
            wall,mono=self.wall(),self.monotonic(); key=(scope,component)
            previous=self.samples.get(key)
            if previous and previous[:2]==(state,reason) and (state!='healthy' or mono-previous[2]<2):
                return
            with closing(self._db()) as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('''INSERT INTO component_health VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(scope,component) DO UPDATE SET state=excluded.state,
                    reason=excluded.reason,checked=excluded.checked,session=excluded.session,
                    last_success=COALESCE(excluded.last_success,component_health.last_success)''',
                    (scope,component,state,reason,wall,wall if state=='healthy' else None,self.session))
                db.execute('INSERT OR REPLACE INTO health_context VALUES (1,?)',(scope,))
                db.commit()
            self.samples[key]=(state,reason,mono)
            if state=='healthy': self.successes[key]=mono

    def snapshot(self, scope, active=()):
        with self.lock, closing(self._db()) as db:
            saved={r['component']:dict(r) for r in db.execute('SELECT * FROM component_health WHERE scope=?',(scope,))}
            wall,mono=self.wall(),self.monotonic()
            drift=abs((wall-self.origin[0])-(mono-self.origin[1]))>5
            rows=[]
            for component,(label,ttl,hint) in COMPONENTS.items():
                old=saved.get(component,{})
                age=max(0,round(mono-self.successes[(scope,component)])) if (scope,component) in self.successes else None
                state=old.get('state','waiting') if old.get('session')==self.session else 'waiting'
                if component not in active: state='stopped'
                elif state=='healthy':
                    if drift: state='clock_changed'
                    elif age is None or age>=ttl: state='stale'
                if state=='clock_changed': hint='Check the PC clock; reconnect to establish fresh evidence.'
                rows.append(dict(component=component,label=label,state=state,
                    reason=old.get('reason') if old.get('session')==self.session else None,
                    last_success=old.get('last_success'),age_seconds=age,recovery=hint))
            return rows
