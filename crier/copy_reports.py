"""Independent durable telemetry; it never changes execution decisions."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
import httpx
from .copy_dashboard import StatusReport, PresenceReport


class CopyReporter:
    def __init__(self,device):
        self.device=device; self.changed=asyncio.Event(); self.results={}; self.metadata={}
        with device.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS copy_revision(pair TEXT PRIMARY KEY,revision INTEGER);
            CREATE TABLE IF NOT EXISTS copy_outbox(pair TEXT,slot TEXT,payload TEXT,identity TEXT,pending INTEGER,PRIMARY KEY(pair,slot));
            ''')

    def queue(self,pair,slot,value):
        identity=json.dumps({k:v for k,v in value.items() if k not in ('revision','observed_at')},sort_keys=True)
        with self.device.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT identity FROM copy_outbox WHERE pair=? AND slot=?',(pair,slot)).fetchone()
            if slot!='presence' and old and old[0]==identity: return
            row=db.execute('SELECT revision FROM copy_revision WHERE pair=?',(pair,)).fetchone()
            revision=(row[0] if row else 0)+1
            value=dict(value,revision=revision)
            parsed=(PresenceReport if slot=='presence' else StatusReport).model_validate(value)
            db.execute('INSERT OR REPLACE INTO copy_revision VALUES (?,?)',(pair,revision))
            db.execute('INSERT OR REPLACE INTO copy_outbox VALUES (?,?,?,?,1)',(pair,slot,parsed.model_dump_json(),identity))

    def collect(self):
        device=self.device; engine=device.engine
        if not engine: return []
        # One SQLite read transaction prevents counters and their prices tearing.
        with engine._db() as db:
            db.execute('BEGIN')
            trades=[json.loads(r['data']) for r in db.execute('SELECT data FROM intent_trades')]
            orders=[dict(r) for r in db.execute('SELECT * FROM intent_orders')]
            evidence={r[0]:json.loads(r[1]) for r in db.execute('SELECT cid,data FROM intent_policy_evidence')}
            plans={r[0]:json.loads(r[1]) for r in db.execute('SELECT event_id,data FROM intent_policy_plan')}
        reports=[]
        for e in trades:
            local=[o for o in orders if o['trade_id']==e['trade_id']]
            result=self.results.get(e['trade_id'],{})
            quantities={}; costs={}
            with localcontext() as context:
                context.prec=256
                for side in ('buy','sell'):
                    selected=[o for o in local if o['side']==side]
                    total=sum((Decimal(o['filled']) for o in selected),Decimal(0))
                    if total!=int(total): raise ValueError('Fractional tracked fills unsupported')
                    quantities[side]=int(total); cost=Decimal(0)
                    for order in selected:
                        count=Decimal(order['filled'])
                        if not count: continue
                        ev=evidence.get(order['cid'],{})
                        if ev.get('average') is None or Decimal(ev.get('filled','-1'))!=count:
                            cost=None; break
                        cost+=count*Decimal(ev['average'])
                    costs[side]=format(cost,'f') if cost is not None else None
            bought,sold=quantities['buy'],quantities['sell']
            states={o['status'] for o in local}
            state='received'; reason=None
            if 'unknown' in states: state='unknown'; reason='reconciliation_required'
            elif result.get('reconciliation_required') or result.get('state') in ('reconcile_required','waiting_for_reconciliation'):
                state='blocked'; reason='reconciliation_required'
            elif bought and sold==bought: state='closed'
            elif 'pending_cancel' in states: state='cancel_pending'
            elif 'partially_filled' in states: state='partially_filled'
            elif states & {'new','accepted','pending_new','held','pending_replace'}: state='working'
            elif bought: state='filled'
            elif states & {'canceled','expired'}: state='canceled'
            elif states & {'rejected','skipped'}: state='not_submitted'; reason='not_submitted'
            elif not engine.load_settings()['enabled']: state='blocked'; reason='entries_paused'
            plan=plans.get(e['event_id'],{})
            metadata=plan.get('metadata') or self.metadata.get(e['trade_id']) or {}
            verified=(metadata.get('environment')==e['environment'] and metadata.get('symbol')==e['symbol']
                      and metadata.get('asset')==e['asset'] and metadata.get('currency')=='USD'
                      and metadata.get('multiplier')==(100 if e['asset']=='option' else 1))
            timeline=device.trade_trace(e['trade_id'])
            observed=[r['timestamp'] for r in timeline if r['stage']=='broker_reconciled']
            quotes=[r['details']['observation'].get('quote') for r in timeline if r['stage']=='diagnostic_observation'
                    and r['details'].get('actor') in ('host' if device.pair['role']=='host' else 'local',)
                    and r['details'].get('observation',{}).get('quote_error') is None]
            reports.append(dict(version=1,event_id=e['event_id'],observed_at=datetime.now(timezone.utc).isoformat(),
                broker_observed_at=max(observed) if observed else None,state=state,target_quantity=plan.get('target'),
                bought=bought,sold=sold,buy_premium=costs['buy'],sell_premium=costs['sell'],
                currency='USD' if verified else None,multiplier=metadata['multiplier'] if verified else None,
                fees=None,quote=quotes[-1] if quotes else None,reason=reason))
        return reports

    async def metadata_loop(self,stop):
        """Read-only broker metadata is optional and never awaited by execution."""
        attempted=set()
        while not stop.is_set():
            device=self.device; engine=device.engine; scope=device.fingerprint
            if engine and hasattr(device.broker,'metadata'):
                for trade in engine.status()['trades'][-50:]:
                    key=(scope,trade['id'])
                    if key in attempted: continue
                    attempted.add(key)
                    task=asyncio.create_task(asyncio.to_thread(device.broker.metadata,trade['event']))
                    try:
                        value=await asyncio.shield(task)
                        if not stop.is_set() and scope==device.fingerprint:
                            self.metadata[trade['id']]=value; self.changed.set()
                    except asyncio.CancelledError:
                        await asyncio.gather(task,return_exceptions=True); raise
                    except Exception: pass
                    if stop.is_set(): break
            try: await asyncio.wait_for(stop.wait(),15)
            except TimeoutError: pass

    async def run(self,stop):
        metadata=asyncio.create_task(self.metadata_loop(stop)); presence_at=0; presence_state=None
        try:
            async with httpx.AsyncClient(timeout=10,follow_redirects=False,trust_env=False) as client:
                while not stop.is_set():
                    self.changed.clear(); device=self.device; scope=device.fingerprint; pair=dict(device.pair or {})
                    if pair and device.engine:
                        try:
                            for report in self.collect(): self.queue(scope,'status:'+report['event_id'],report)
                            now=asyncio.get_running_loop().time()
                            current_presence=(scope,device.transport,device.engine.load_settings()['enabled'])
                            if now>=presence_at or current_presence!=presence_state:
                                self.queue(scope,'presence',dict(version=1,observed_at=datetime.now(timezone.utc).isoformat(),platform='windows',
                                    transport=device.transport,entries_enabled=device.engine.load_settings()['enabled']))
                                presence_at=now+15; presence_state=current_presence
                            with device.db() as db:
                                rows=db.execute('SELECT slot,payload FROM copy_outbox WHERE pair=? AND pending=1 ORDER BY slot LIMIT 100',(scope,)).fetchall()
                            for row in rows:
                                if stop.is_set() or scope!=device.fingerprint: break
                                route='presence' if row['slot']=='presence' else 'status'
                                response=await client.post(pair['url'].rstrip('/')+'/api/sync/'+route,
                                    headers={'Authorization':'Bearer '+pair['token']},content=row['payload'])
                                response.raise_for_status()
                                with device.db() as db:
                                    db.execute('UPDATE copy_outbox SET pending=0 WHERE pair=? AND slot=? AND payload=?',(scope,row['slot'],row['payload']))
                        except Exception: pass  # Observational errors never alter the engine or event cursor.
                    try: await asyncio.wait_for(self.changed.wait(),2)
                    except TimeoutError: pass
        finally:
            metadata.cancel(); await asyncio.gather(metadata,return_exceptions=True)
