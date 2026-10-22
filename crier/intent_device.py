"""Local PC host/follower. Relay delivery and broker execution run independently."""
import asyncio
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import threading
import time
import random
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
from pydantic import ValidationError
from .device_secrets import save_secret,load_secret
from .intent_protocol import IntentEvent
from .intent_engine import IntentEngine
from .diagnostics_client import DiagnosticsClient
from .trade_diagnostics import trade_report, export_trade_json, export_trade_csv

class IntentDevice:
    def __init__(self,folder,broker=None):
        self.folder=Path(folder); self.folder.mkdir(parents=True,exist_ok=True)
        self.path=self.folder/'intent-device.sqlite3'; self.broker=broker
        self.pair=None; self.engine=None; self.message='Not paired'; self.lock=threading.RLock()
        self.changed=asyncio.Event()
        self.publish_changed=asyncio.Event()
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS outgoing(id TEXT PRIMARY KEY,pair TEXT,trade_id TEXT,sequence INTEGER,action TEXT,payload TEXT,state TEXT);
            CREATE TABLE IF NOT EXISTS cursors(pair TEXT PRIMARY KEY,cursor INTEGER);
            CREATE TABLE IF NOT EXISTS quarantined_events(pair TEXT,cursor INTEGER,payload TEXT,error TEXT,PRIMARY KEY(pair,cursor));
            CREATE TABLE IF NOT EXISTS device_trace(id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT,monotonic_ns INTEGER,trade_id TEXT,stage TEXT,details TEXT);''')
        self.diagnostics=DiagnosticsClient(self)
        secret=self.folder/'intent-pairing.secret'
        if secret.exists():
            self.pair=json.loads(load_secret(secret)); self._engine()
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15); db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    def _trace(self,trade_id,stage,**details):
        """Diagnostic metadata only; never log pairing tokens or raw payloads."""
        try:
            with self.db() as db:
                db.execute('INSERT INTO device_trace(timestamp,monotonic_ns,trade_id,stage,details) VALUES (?,?,?,?,?)',
                           (datetime.now(timezone.utc).isoformat(),time.monotonic_ns(),trade_id,stage,json.dumps(details,sort_keys=True)))
        except (sqlite3.Error,TypeError,ValueError):
            pass

    def trade_trace(self,trade_id):
        with self.db() as db:
            device=[dict(timestamp=r['timestamp'],monotonic_ns=r['monotonic_ns'],trade_id=r['trade_id'],
                         stage=r['stage'],details=json.loads(r['details']))
                    for r in db.execute('SELECT * FROM device_trace WHERE trade_id=? ORDER BY id',(trade_id,))]
        engine=self.engine.trade_trace(trade_id) if self.engine and hasattr(self.engine,'trade_trace') else []
        for entry in device:
            entry['event_id'] = entry['details'].get('event_id')
        return sorted(device+engine,key=lambda row:row['timestamp'])

    def trade_report(self, trade_id, side='buy'):
        return trade_report(self.trade_trace(trade_id), side)

    def export_trade(self, trade_id, format='json', side='buy'):
        report = self.trade_report(trade_id, side)
        if not report['timeline']:
            raise ValueError('Unknown trade or no recorded diagnostic events')
        if format == 'json':
            return export_trade_json(report)
        if format == 'csv':
            return export_trade_csv(report)
        raise ValueError('Unsupported diagnostics export format')

    @property
    def fingerprint(self): return sha256(json.dumps(self.pair,sort_keys=True).encode()).hexdigest() if self.pair else ''
    def _engine(self):
        self.engine=IntentEngine(self.folder/('intent-'+self.fingerprint+'.sqlite3'),self.broker) if self.broker and self.pair else None
    def configure(self,pair):
        if set(pair)!={'url','token','environment','role'}: raise ValueError('Paste a complete intent pairing')
        url=urlsplit(pair['url'])
        local=url.scheme=='http' and url.hostname in ('127.0.0.1','localhost','::1')
        if ((url.scheme!='https' and not local) or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/')):
            raise ValueError('Use an HTTPS origin (localhost HTTP for PC development only)')
        if not isinstance(pair['token'],str) or not 32<=len(pair['token'])<=256 or pair['environment'] not in ('paper','live') or pair['role'] not in ('host','follower'):
            raise ValueError('Invalid intent pairing')
        with self.lock:
            if self.pair==pair: return
            if self.engine:
                orders=self.engine.status()['orders']
                from .intent_engine import TERMINAL
                if any(o['status'] not in TERMINAL for o in orders): raise ValueError('Resolve working orders before changing pairing')
                from decimal import Decimal
                positions={}
                for order in orders: positions[order['trade_id']]=positions.get(order['trade_id'],Decimal(0))+Decimal(order['filled'])*(1 if order['side']=='buy' else -1)
                if any(q>0 for q in positions.values()): raise ValueError('Close tracked positions before changing pairing')
            save_secret(self.folder/'intent-pairing.secret',json.dumps(pair))
            self.pair=dict(pair); self._engine(); self.message='Paired; broker credentials required' if not self.engine else 'Paired'
            if self.engine and pair['role']=='host': self.engine.save_settings({'enabled':True})
    def status(self):
        return {'pair':{k:v for k,v in (self.pair or {}).items() if k!='token'},'configured':self.engine is not None,
                'message':self.message,'execution':self.engine.status() if self.engine else None}
    def command(self,action,trade_id=None,**values):
        with self.lock:
            if not self.pair or self.pair['role']!='host' or not self.engine: raise ValueError('Connect a host pairing and broker first')
            if action in ('enter','replace') and not self.engine.load_settings()['enabled']: raise ValueError('Enable this device before submitting')
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if action=='enter':
                    if trade_id: raise ValueError('New entry creates a fresh trade identity')
                    trade_id=str(uuid4()); sequence=1
                else:
                    row=db.execute('SELECT payload FROM outgoing WHERE pair=? AND trade_id=? ORDER BY sequence DESC LIMIT 1',(self.fingerprint,trade_id)).fetchone()
                    if not row: raise ValueError('Select a tracked trade')
                    prior=json.loads(row['payload']); sequence=prior['sequence']+1
                    if any(k in values and values[k]!=prior[k] for k in ('symbol','asset')):
                        raise ValueError('Trade identity cannot change')
                    if prior['action'] in ('cancel','exit') and action in ('enter','replace'): raise ValueError('Invalidated entry cannot be reopened')
                    values={k:values.get(k,prior[k]) for k in ('symbol','asset','quantity','limit_price')}
                now=datetime.now(timezone.utc)
                event=IntentEvent(version=1,event_id=str(uuid4()),trade_id=trade_id,sequence=sequence,action=action,
                                  environment=self.pair['environment'],created_at=now,expires_at=now+timedelta(seconds=10),**values)
                db.execute('INSERT INTO outgoing VALUES (?,?,?,?,?,?,?)',(event.event_id,self.fingerprint,trade_id,sequence,action,event.model_dump_json(),'pending'))
            self._trace(event.trade_id,'sender_instruction_journaled',event_id=event.event_id,action=event.action,sequence=event.sequence,reference_limit_price=str(event.limit_price),quote_status='not_captured')
            try: self.diagnostics.observe(event,'sender')
            except Exception: pass
            self.engine.accept(event)
            self.changed.set()
            self.publish_changed.set()
            return event
    def outgoing(self):
        if not self.pair: return []
        with self.db() as db:
            # A queued cancellation supersedes older unsent entries before reconnection.
            db.execute("""UPDATE outgoing SET state='superseded' WHERE pair=? AND state='pending' AND action IN ('enter','replace')
                AND EXISTS (SELECT 1 FROM outgoing newer WHERE newer.pair=outgoing.pair AND newer.trade_id=outgoing.trade_id AND newer.sequence>outgoing.sequence AND newer.action IN ('cancel','exit'))""",(self.fingerprint,))
            return [dict(r) for r in db.execute("SELECT * FROM outgoing WHERE pair=? AND state='pending' ORDER BY CASE WHEN action IN ('cancel','exit') THEN 0 ELSE 1 END,sequence",(self.fingerprint,))]
    async def publish_loop(self,stop):
        async with httpx.AsyncClient(timeout=10,follow_redirects=False,trust_env=False) as client:
            failures=0
            while not stop.is_set():
                self.publish_changed.clear()
                if self.pair and self.pair['role']=='host' and self.engine:
                    for row in self.outgoing():
                        if stop.is_set(): break
                        try:
                            # Restore local execution after a crash between outbox commit and accept.
                            self.engine.accept(IntentEvent.model_validate_json(row['payload']))
                            pair=dict(self.pair)
                            self._trace(row['trade_id'],'relay_publish_started',event_id=row['id'])
                            response=await client.post(pair['url'].rstrip('/')+'/api/sync/events',headers={'Authorization':'Bearer '+pair['token']},json=json.loads(row['payload']))
                            response.raise_for_status()
                            with self.db() as db: db.execute("UPDATE outgoing SET state='sent' WHERE id=?",(row['id'],))
                            self._trace(row['trade_id'],'relay_publish_acknowledged',event_id=row['id'],http_status=response.status_code)
                            self.message='Intent delivered'
                            failures=0
                        except httpx.HTTPStatusError as exc:
                            failures+=1
                            if exc.response.status_code in (401,403,409):
                                self.message='Relay rejected delivery; check pairing or channel. Queue retained.'
                            else:
                                self.message='Relay delivery pending; retrying with backoff'
                            break
                        except Exception:
                            failures+=1
                            self.message='Relay delivery pending; retrying with backoff'
                            break
                if failures:
                    # Preserve outbox order and avoid hammering an unavailable relay.
                    delay=min(60,2**min(failures,6))+random.uniform(0,1)
                    try: await asyncio.wait_for(stop.wait(),delay)
                    except TimeoutError: pass
                    continue
                try: await asyncio.wait_for(self.publish_changed.wait(),.1 if self.outgoing() else .5)
                except TimeoutError: pass
    async def receive_loop(self,stop):
        async with httpx.AsyncClient(timeout=26,follow_redirects=False,trust_env=False) as client:
            while not stop.is_set():
                if not self.pair or self.pair['role']!='follower' or not self.engine:
                    try: await asyncio.wait_for(stop.wait(),.5)
                    except TimeoutError: pass
                    continue
                pair=dict(self.pair); fingerprint=self.fingerprint; engine=self.engine
                with self.db() as db: row=db.execute('SELECT cursor FROM cursors WHERE pair=?',(fingerprint,)).fetchone()
                try:
                    response=await client.get(pair['url'].rstrip('/')+'/api/sync/events',params={'after':row[0] if row else 0,'wait':20},headers={'Authorization':'Bearer '+pair['token']})
                    response.raise_for_status()
                    if fingerprint!=self.fingerprint: continue
                    quarantined=False
                    for item in response.json()['events']:
                        try:
                            event=IntentEvent.model_validate(item['event'])
                        except (ValidationError, ValueError, TypeError) as exc:
                            # Only schema-invalid events are quarantined. Do not
                            # bypass environment, identity, or execution errors.
                            with self.db() as db:
                                db.execute('BEGIN IMMEDIATE')
                                db.execute('INSERT OR IGNORE INTO quarantined_events VALUES (?,?,?,?)',
                                           (fingerprint,item['cursor'],json.dumps(item.get('event'),default=str),type(exc).__name__))
                                db.execute('INSERT OR REPLACE INTO cursors VALUES (?,?)',(fingerprint,item['cursor']))
                            quarantined=True
                            continue
                        if event.environment!=pair['environment']: raise ValueError('Pair environment mismatch')
                        self._trace(event.trade_id,'receiver_instruction_arrived',event_id=event.event_id,sequence=event.sequence,relay_cursor=item['cursor'],sender_created_at=event.created_at.isoformat(),reference_limit_price=str(event.limit_price),quote_status='not_captured')
                        try: self.diagnostics.observe(event,'receiver')
                        except Exception: pass
                        engine.accept(event)
                        self._trace(event.trade_id,'receiver_instruction_stored',event_id=event.event_id,relay_cursor=item['cursor'])
                        self.changed.set()
                        with self.db() as db: db.execute('INSERT OR REPLACE INTO cursors VALUES (?,?)',(fingerprint,item['cursor']))
                    self.message='Following; invalid relay event quarantined for inspection' if quarantined else 'Following; connected'
                except Exception:
                    self.message='Receiver disconnected; reconnecting without replaying expired entries'
                    try: await asyncio.wait_for(stop.wait(),1)
                    except TimeoutError: pass
    async def diagnostics_loop(self,stop):
        await self.diagnostics.run(stop)

    async def execute_loop(self,stop):
        while not stop.is_set():
            self.changed.clear()
            if self.engine:
                try:
                    results=await asyncio.to_thread(self.engine.tick)
                    if self.pair and self.pair['role']=='host':
                        for result in results:
                            if result.get('state')=='rejected':
                                with self.db() as db: row=db.execute('SELECT action FROM outgoing WHERE pair=? AND trade_id=? ORDER BY sequence DESC LIMIT 1',(self.fingerprint,result['trade_id'])).fetchone()
                                if row and row[0] in ('enter','replace'): self.command('cancel',trade_id=result['trade_id'])
                except Exception: self.message='Execution requires reconciliation; inspect saved orders'
            try: await asyncio.wait_for(self.changed.wait(),2)
            except TimeoutError: pass
