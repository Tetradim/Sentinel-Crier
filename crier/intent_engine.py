"""Durable intent executor. Receipt never waits on broker network operations."""
from datetime import datetime, timezone
from contextlib import contextmanager
from .intent_broker import BrokerNotSubmitted, BrokerSuperseded
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import json
import sqlite3
import threading
import time
from uuid import uuid4
from dataclasses import asdict
from .execution_policy import ExecutionPolicy
from .policy_journal import PolicyJournal
from .intent_protocol import IntentEvent
from .trade_diagnostics import validate_quote, trade_report, export_trade_json, export_trade_csv
from .lock import single_process, AlreadyRunningError
from .entry_clock import EntryClock, ClockUncertain
from .error_log import emit_error

DEFAULTS = dict(enabled=False, mode='exact_limit', max_slippage_bps=100,
                max_slippage_amount='0.02', max_age_seconds=10, max_quantity=1000, execution_policy=None)
TERMINAL = {'filled', 'canceled', 'expired', 'rejected', 'replaced', 'skipped'}
BROKER_STATUSES = {'new', 'accepted', 'pending_new', 'accepted_for_bidding',
                   'partially_filled', 'filled', 'done_for_day', 'canceled',
                   'expired', 'replaced', 'pending_cancel', 'pending_replace',
                   'stopped', 'rejected', 'suspended', 'calculated'}

class IntentEngine(PolicyJournal):
    policy_terminal = TERMINAL
    def __init__(self, path, broker, clock=None, *, entry_clock=None, pairing_id=None, role=None, monotonic=None, error_log=None):
        self.error_log = error_log
        self.path, self.broker = str(path), broker
        self.pairing_id,self.role=pairing_id,role
        self.monotonic=monotonic or time.monotonic
        self.policy_session=str(uuid4())
        self.clock = clock or time.time
        self.entry_clock = entry_clock or EntryClock()
        self.worker = threading.Lock()
        with self._db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS intent_events(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS intent_trades(id TEXT PRIMARY KEY, data TEXT NOT NULL, invalid INTEGER NOT NULL, skipped INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS intent_orders(cid TEXT PRIMARY KEY, trade_id TEXT, sequence INTEGER, side TEXT, qty TEXT, status TEXT, broker_id TEXT, filled TEXT);
            CREATE TABLE IF NOT EXISTS intent_settings(id INTEGER PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS intent_pin(id INTEGER PRIMARY KEY, environment TEXT, account TEXT);
            CREATE TABLE IF NOT EXISTS intent_cancel_requested(cid TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS intent_settled(id TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS intent_decisions(event_id TEXT PRIMARY KEY, trade_id TEXT, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS intent_trace(id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, monotonic_ns INTEGER NOT NULL, trade_id TEXT NOT NULL, event_id TEXT, stage TEXT NOT NULL, details TEXT NOT NULL);''')
            if 'attempted_at' not in {r[1] for r in db.execute('PRAGMA table_info(intent_cancel_requested)')}:
                db.execute('ALTER TABLE intent_cancel_requested ADD COLUMN attempted_at REAL')
            db.commit()
            self.migrate_policies(db)
    @contextmanager
    def _db(self):
        db=sqlite3.connect(self.path, timeout=30)
        db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    def _trace(self, trade_id, stage, event_id=None, **details):
        """Best-effort diagnostics; never affect broker execution decisions."""
        try:
            with self._db() as db:
                db.execute('INSERT INTO intent_trace(timestamp,monotonic_ns,trade_id,event_id,stage,details) VALUES (?,?,?,?,?,?)',
                           (datetime.now(timezone.utc).isoformat(),time.monotonic_ns(),trade_id,event_id,stage,json.dumps(details,sort_keys=True)))
        except (sqlite3.Error, TypeError, ValueError):
            pass

    def trade_trace(self, trade_id):
        """Chronological evidence without credentials or raw broker responses."""
        with self._db() as db:
            return [dict(timestamp=r['timestamp'],monotonic_ns=r['monotonic_ns'],
                         trade_id=r['trade_id'],event_id=r['event_id'],stage=r['stage'],
                         details=json.loads(r['details']))
                    for r in db.execute('SELECT * FROM intent_trace WHERE trade_id=? ORDER BY id',(trade_id,))]

    def record_quote(self, trade_id, observation_stage, quote):
        """Persist a real quote from an external market-data feed.

        No broker request is made here; caller supplies the observed quote.
        """
        if observation_stage not in ('sender','receiver','broker_submit','fill'):
            raise ValueError('Invalid quote observation stage')
        normalized=validate_quote(quote)
        with self._db() as db:
            trade=db.execute('SELECT data FROM intent_trades WHERE id=?',(trade_id,)).fetchone()
            if not trade:
                raise ValueError('Unknown trade')
            db.execute('INSERT INTO intent_trace(timestamp,monotonic_ns,trade_id,event_id,stage,details) VALUES (?,?,?,?,?,?)',
                       (datetime.now(timezone.utc).isoformat(),time.monotonic_ns(),trade_id,json.loads(trade[0])['event_id'],
                        'market_quote_observed',json.dumps(dict(normalized,observation_stage=observation_stage),sort_keys=True)))
        return normalized

    def trade_report(self, trade_id, side='buy'):
        return trade_report(self.trade_trace(trade_id),side)

    def export_trade(self, trade_id, format='json', side='buy'):
        report=self.trade_report(trade_id,side)
        if not report['timeline']:
            raise ValueError('Unknown trade or no recorded diagnostic events')
        if format=='json':
            return export_trade_json(report)
        if format=='csv':
            return export_trade_csv(report)
        raise ValueError('Unsupported diagnostics export format')

    def load_settings(self):
        with self._db() as db: row=db.execute('SELECT data FROM intent_settings WHERE id=1').fetchone()
        saved=dict(DEFAULTS, **(json.loads(row[0]) if row else {}))
        return self._validate_settings(saved,{})
    def save_settings(self, settings):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM intent_settings WHERE id=1').fetchone()
            old=dict(DEFAULTS,**(json.loads(row[0]) if row else {}))
            s=self._validate_settings(old,settings)
            db.execute('INSERT OR REPLACE INTO intent_settings VALUES (1,?)',(json.dumps(s),))
        return s
    def _validate_settings(self, old, settings):
        s=dict(old, **settings)
        if set(s)!=set(DEFAULTS) or type(s['enabled']) is not bool or s['mode'] not in {'exact_limit','market','bounded_limit'}: raise ValueError('Invalid intent settings')
        for key,lo,hi in [('max_age_seconds',1,30),('max_quantity',1,1000),('max_slippage_bps',0,10000)]:
            if type(s[key]) is not int or not lo<=s[key]<=hi: raise ValueError('Invalid '+key)
        amount=Decimal(str(s['max_slippage_amount']))
        if not amount.is_finite() or amount<0: raise ValueError('Invalid slippage')
        s['max_slippage_amount']=str(amount)
        if s['execution_policy'] is not None:
            if self.role!='follower' or not self.pairing_id: raise ValueError('Follower pairing required')
            s['execution_policy']=asdict(ExecutionPolicy.parse(s['execution_policy']))
            if s['mode']=='market' and (s['execution_policy']['mode']=='budget' or s['execution_policy']['max_entry_notional'] is not None):
                raise ValueError('Budget and notional policies require limit pricing')
        if s['execution_policy']!=old['execution_policy'] and s['enabled']:
            raise ValueError('Save policy with entries paused')
        return s
    def accept(self, event):
        e=IntentEvent.model_validate(event).to_dict() if isinstance(event,dict) else IntentEvent.model_validate(event.to_dict()).to_dict()
        encoded=json.dumps(e,sort_keys=True,default=lambda x:x.isoformat())
        e=json.loads(encoded)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            saved=db.execute('SELECT data FROM intent_settings WHERE id=1').fetchone()
            settings=dict(DEFAULTS,**(json.loads(saved[0]) if saved else {}))
            old=db.execute('SELECT data FROM intent_events WHERE id=?',(e['event_id'],)).fetchone()
            if old:
                if old[0]!=encoded: raise ValueError('Event identity changed')
                return {'state':'duplicate'}
            row=db.execute('SELECT * FROM intent_trades WHERE id=?',(e['trade_id'],)).fetchone()
            prior=json.loads(row['data']) if row else None
            if prior and any(prior[k]!=e[k] for k in ('environment','symbol','asset')): raise ValueError('Trade identity changed')
            if prior and prior['sequence']==e['sequence'] and prior!=e: raise ValueError('Revision conflict')
            invalid=bool(row and row['invalid']) or e['action'] in ('cancel','exit')
            skipped=bool(row and row['skipped']) or (e['action'] in ('enter','replace') and not settings['enabled'])
            db.execute('INSERT INTO intent_events VALUES (?,?)',(e['event_id'],encoded))
            db.execute('INSERT INTO intent_event_index VALUES (?,?,?)',(e['event_id'],e['trade_id'],e['sequence']))
            if row is None: self.snapshot_policy(db,e,settings)
            desired=encoded if not prior or e['sequence']>prior['sequence'] else row['data']
            db.execute('INSERT OR REPLACE INTO intent_trades VALUES (?,?,?,?)',(e['trade_id'],desired,invalid,skipped))
            if e['action'] in ('enter','replace') and not settings['enabled']:
                db.execute('INSERT OR IGNORE INTO intent_decisions VALUES (?,?,?)',
                           (e['event_id'],e['trade_id'],json.dumps(dict(state='skipped',reason='entries_paused'))))
        self._trace(e['trade_id'],'instruction_stored',e['event_id'],action=e['action'],sequence=e['sequence'],symbol=e['symbol'],asset=e['asset'],quantity=e['quantity'],limit_price=e['limit_price'],sender_created_at=e['created_at'],expires_at=e['expires_at'])
        return {'state':'stored','trade_id':e['trade_id']}
    def status(self):
        with self._db() as db:
            trades=[dict(id=r['id'], event=json.loads(r['data']), invalid=bool(r['invalid']), skipped=bool(r['skipped'])) for r in db.execute('SELECT * FROM intent_trades')]
            orders=[dict(r) for r in db.execute('SELECT * FROM intent_orders')]
            pin=db.execute('SELECT environment,account FROM intent_pin WHERE id=1').fetchone()
            policies={r[0]:json.loads(r[1]) for r in db.execute('SELECT id,data FROM intent_policy_trade')}
            plans={r[0]:json.loads(r[1]) for r in db.execute('SELECT event_id,data FROM intent_policy_plan')}
        return {'settings':self.load_settings(),'trades':trades,'orders':orders,'pin':dict(pin) if pin else None,'policies':policies,'plans':plans}
    def _orders(self, tid):
        with self._db() as db: return [dict(r) for r in db.execute('SELECT * FROM intent_orders WHERE trade_id=?',(tid,))]
    def _reconcile(self, order):
        if order['status'] in ('skipped','rejected') and order['broker_id'] is None and Decimal(order['filled'])==0:
            # These states are written only on a definitive local no-POST outcome.
            # Unknown submissions never acquire a terminal status without broker proof.
            return True
        snap=self.broker.lookup(order['cid'])
        if snap is None:
            self._trace(order['trade_id'],'broker_lookup_unknown',client_order_id=order['cid'])
            return # Unknown stays unknown forever until resolved; never blind POST.
        if snap.get('client_order_id')!=order['cid']: raise ValueError('Broker order identity mismatch')
        if not isinstance(snap.get('id'),str) or not snap['id'].strip(): raise ValueError('Missing broker order ID')
        if order['broker_id'] and snap.get('id')!=order['broker_id']: raise ValueError('Broker order ID changed')
        with self._db() as db:
            trade=json.loads(db.execute('SELECT data FROM intent_trades WHERE id=?',(order['trade_id'],)).fetchone()[0])
        if snap.get('symbol')!=trade['symbol'] or snap.get('side')!=order['side'] or Decimal(str(snap.get('qty','NaN')))!=Decimal(order['qty']): raise ValueError('Broker order binding mismatch')
        filled=Decimal(str(snap['filled_qty']))
        if (not filled.is_finite() or filled<Decimal(order['filled'])
                or filled>Decimal(order['qty']) or filled!=filled.to_integral_value()):
            raise ValueError('Inconsistent broker cumulative quantity')
        if snap.get('status') not in BROKER_STATUSES: raise ValueError('Invalid broker status')
        if snap.get('filled_avg_price') is not None:
            average=Decimal(str(snap['filled_avg_price']))
            if not average.is_finite() or average<=0: raise ValueError('Invalid broker fill price')
        with self._db() as db:
            db.execute('UPDATE intent_orders SET status=?, broker_id=?, filled=? WHERE cid=?',(snap['status'],snap['id'],str(filled),order['cid']))
            self.reconcile_policy_evidence(db,order,snap)
        self._trace(order['trade_id'],'broker_reconciled',client_order_id=order['cid'],status=snap['status'],filled_qty=str(filled),avg_fill_price=str(snap.get('filled_avg_price')) if snap.get('filled_avg_price') is not None else None,broker_created_at=snap.get('created_at'),broker_filled_at=snap.get('filled_at'))
        return True
    def tick(self):
        try:
            with single_process(self.path+'.worker.lock'): return self._tick_locked()
        except AlreadyRunningError: return []
    def _tick_locked(self):
        results=[]
        if not self.worker.acquire(False): return results
        try:
            with self._db() as db: ids=[r[0] for r in db.execute('SELECT t.id FROM intent_trades t LEFT JOIN intent_settled s ON t.id=s.id WHERE s.id IS NULL OR t.data!=s.data')]
            for tid in ids:
                try: results.append(self._step(tid))
                except Exception as exc:
                    emit_error(self.error_log,'intent.execution_failed',exc,trade_id=tid)
                    self._trace(tid,'execution_error',error_type=type(exc).__name__)
                    results.append({'trade_id':tid,'state':'reconcile_required','error':type(exc).__name__})
        finally: self.worker.release()
        return results
    def _settle(self, tid, event, state, *, reason=None):
        with self._db() as db:
            current=db.execute('SELECT data FROM intent_trades WHERE id=?',(tid,)).fetchone()[0]
            if json.loads(current)==event:
                db.execute('INSERT OR REPLACE INTO intent_settled VALUES (?,?)',(tid,current))
                prior=db.execute('SELECT data FROM intent_decisions WHERE event_id=?',(event['event_id'],)).fetchone()
                saved_reason=reason if reason is not None else json.loads(prior[0]).get('reason') if prior else None
                db.execute('INSERT OR REPLACE INTO intent_decisions VALUES (?,?,?)',
                           (event['event_id'],tid,json.dumps(dict(state=state,reason=saved_reason))))
        self._trace(tid,'execution_decision',event.get('event_id'),state=state)
        if hasattr(self.broker,'settled_intent'):
            self.broker.settled_intent(event,state)
        return {'trade_id':tid,'state':state}
    def _step(self, tid):
        with self._db() as db: row=db.execute('SELECT * FROM intent_trades WHERE id=?',(tid,)).fetchone()
        e=json.loads(row['data'])
        account=self.broker.verify(e['environment'])
        if not isinstance(account,str) or not account: raise ValueError('Broker must return verified account identity')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            pin=db.execute('SELECT environment,account FROM intent_pin WHERE id=1').fetchone()
            if pin and tuple(pin)!=(e['environment'],account): raise ValueError('Persisted account/environment mismatch')
            if not pin: db.execute('INSERT INTO intent_pin VALUES (1,?,?)',(e['environment'],account))
        if hasattr(self.broker,'observe_intent'):
            self.broker.observe_intent(e)
        snapshot=self.policy_for(tid,e,account)
        reconciled=set(); failures=[]
        for order in self._orders(tid):
            try:
                if self._reconcile(order): reconciled.add(order['cid'])
            except Exception as exc:
                emit_error(self.error_log,'intent.reconciliation_failed',exc,trade_id=tid,client_order_id=order['cid'])
                failures.append(type(exc).__name__)
                self._trace(tid,'broker_lookup_unusable',client_order_id=order['cid'],error_type=type(exc).__name__)
        orders=self._orders(tid); active=[o for o in orders if o['status'] not in TERMINAL]
        timed_out=self.timed_entry_closed(tid,snapshot,orders)
        cancel=[o for o in active if o['side']=='buy' and (row['invalid'] or row['skipped'] or timed_out or o['sequence']!=e['sequence'])]
        if cancel:
            for order in cancel:
                with self._db() as db:
                    requested=db.execute('SELECT attempted_at FROM intent_cancel_requested WHERE cid=?',(order['cid'],)).fetchone()
                now=self.clock()
                due=not requested or requested['attempted_at'] is None or now-requested['attempted_at']>=5
                if order['broker_id'] and order['cid'] in reconciled and order['status']!='pending_cancel' and due:
                    with self._db() as db:
                        db.execute('INSERT OR REPLACE INTO intent_cancel_requested(cid,attempted_at) VALUES (?,?)',(order['cid'],now))
                        db.execute("UPDATE intent_orders SET status='cancel_unknown' WHERE cid=?",(order['cid'],))
                    self._trace(tid,'cancel_requested',e['event_id'],client_order_id=order['cid'])
                    try:
                        self.broker.cancel(order['broker_id'])
                    except Exception as exc:
                        self._trace(tid,'cancel_uncertain',e['event_id'],client_order_id=order['cid'],error_type=type(exc).__name__)
                        # Preserve the cooldown across failures and process restarts.
                        # A retry always needs another validated broker snapshot.
                        raise
            if any(order['cid'] in reconciled and order['broker_id'] for order in cancel):
                pending={'trade_id':tid,'state':'cancel_pending'}
                if failures or any(order['cid'] not in reconciled for order in orders):
                    pending['reconciliation_required']=True
                return pending
            if failures: return {'trade_id':tid,'state':'reconcile_required','error':failures[0]}
            return {'trade_id':tid,'state':'waiting_for_reconciliation'}
        if failures: return {'trade_id':tid,'state':'reconcile_required','error':failures[0]}
        if any(order['cid'] not in reconciled for order in orders):
            self._trace(tid,'execution_deferred',e['event_id'],reason='prior_order_evidence_unavailable')
            return {'trade_id':tid,'state':'waiting_for_reconciliation'}
        if active: return {'trade_id':tid,'state':'working'}
        settings=self.load_settings(); action=e['action']; side='sell' if action=='exit' else 'buy'
        if action=='cancel' or (side=='buy' and (row['invalid'] or row['skipped'] or timed_out)): return self._settle(tid,e,'invalidated')
        try:
            sample=self.entry_clock.read() if side=='buy' else None
            now=datetime.fromtimestamp(sample.effective,timezone.utc) if sample else datetime.now(timezone.utc)
            start_now=datetime.fromtimestamp(sample.wall,timezone.utc) if sample else now
        except ClockUncertain:
            self._trace(tid,'execution_deferred',e['event_id'],reason='clock_changed')
            return {'trade_id':tid,'state':'waiting_for_clock'}
        if side=='buy' and start_now<datetime.fromisoformat(e['created_at'].replace('Z','+00:00')):
            # A future-dated event is not permanently invalid: wait for its
            # validity window. Later revisions must remain eligible.
            self._trace(tid,'execution_deferred',e['event_id'],reason='future_created_at',sender_created_at=e['created_at'])
            return {'trade_id':tid,'state':'waiting_for_start'}
        if side=='buy' and (not settings['enabled'] or now>=datetime.fromisoformat(e['expires_at'].replace('Z','+00:00')) or (now-datetime.fromisoformat(e['created_at'].replace('Z','+00:00'))).total_seconds()>settings['max_age_seconds'] or e['quantity']>settings['max_quantity']):
            reason='entries_paused' if not settings['enabled'] else 'expired' if now>=datetime.fromisoformat(e['expires_at'].replace('Z','+00:00')) else 'max_age' if (now-datetime.fromisoformat(e['created_at'].replace('Z','+00:00'))).total_seconds()>settings['max_age_seconds'] else 'max_quantity'
            self._trace(tid,'entry_skipped',e['event_id'],reason=reason)
            with self._db() as db:
                db.execute('UPDATE intent_trades SET skipped=1 WHERE id=?',(tid,))
                db.execute('INSERT OR REPLACE INTO intent_decisions VALUES (?,?,?)',
                           (e['event_id'],tid,json.dumps(dict(state='skipped',reason=reason))))
            return self._settle(tid,e,'skipped',reason=reason)
        bought=sum((Decimal(o['filled']) for o in orders if o['side']=='buy'),Decimal(0))
        sold=sum((Decimal(o['filled']) for o in orders if o['side']=='sell'),Decimal(0))
        revision_exits=[o for o in orders if o['side']=='sell' and o['sequence']==e['sequence']]
        revision_sold=sum((Decimal(o['filled']) for o in revision_exits),Decimal(0))
        if side=='sell':
            if any(o['status']!='filled' for o in revision_exits):
                return self._settle(tid,e,'manual_reconcile')
            remaining=min(Decimal(e['quantity'])-revision_sold,bought-sold)
            if snapshot:
                exit_mode=snapshot['policy']['exit_mode']
                if exit_mode=='close_tracked': remaining=bought-sold
                elif exit_mode=='proportional': remaining=self.proportional_due(tid,e,bought,sold)
            if remaining<=0: return self._settle(tid,e,'settled')
            available=Decimal(str(self.broker.position(e['symbol'])))
            if not available.is_finite(): raise ValueError('Invalid available holdings')
            qty=min(remaining,max(Decimal(0),available))
        else:
            qty=Decimal(e['quantity'])-bought
        qty=qty.to_integral_value(rounding=ROUND_DOWN)
        cid='si-'+e['event_id']+('-s'+str(len(revision_exits)) if side=='sell' else '-b')
        if hasattr(self.broker,'make_order_id'):
            cid=self.broker.make_order_id(e,side,len(revision_exits) if side=='sell' else 0)
        if side=='sell' and qty<=0: return {'trade_id':tid,'state':'waiting_for_availability'}
        if any(o['cid']==cid and o['status']=='rejected' for o in orders): return self._settle(tid,e,'rejected')
        if (qty<=0 and not snapshot) or any(o['cid']==cid for o in orders): return self._settle(tid,e,'settled')
        request=dict(symbol=e['symbol'],asset=e['asset'],qty=str(qty),side=side,type='market' if settings['mode']=='market' else 'limit',client_order_id=cid)
        if request['type']=='limit':
            price=Decimal(e['limit_price'])
            if settings['mode']=='bounded_limit':
                delta=min(price*Decimal(settings['max_slippage_bps'])/10000,Decimal(settings['max_slippage_amount']))
                price=price+delta if side=='buy' else price-delta
            tick=Decimal('0.01') if price>=1 or e['asset']=='option' else Decimal('0.0001')
            price=price.quantize(tick,rounding=ROUND_DOWN if side=='buy' else ROUND_UP)
            if price<=0: raise ValueError('Nonpositive bounded price')
            request['limit_price']=str(price)
        plan=None
        if snapshot:
            if side=='buy':
                qty,plan=self.policy_plan(tid,e,snapshot,request,bought,orders,account,settings)
                if qty<=0: return self._settle(tid,e,'settled')
                request['qty']=str(qty)
            else:
                from .execution_policy import validate_metadata
                if not hasattr(self.broker,'metadata') or not hasattr(self.broker,'submit_checked'):
                    raise ValueError('Checked policy broker unavailable')
                request['_policy_metadata']=validate_metadata(self.broker.metadata(e),e,account)
        # Atomic reservation against the newest desired state. Release DB before network.
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            newest=db.execute('SELECT * FROM intent_trades WHERE id=?',(tid,)).fetchone()
            if newest['data']!=row['data'] or (side=='buy' and (newest['invalid'] or newest['skipped'])): return {'trade_id':tid,'state':'superseded'}
            db.execute('INSERT INTO intent_orders VALUES (?,?,?,?,?,?,?,?)',(cid,tid,e['sequence'],side,str(qty),'unknown',None,'0'))
        refusal={'reason':'revision_changed'}
        def can_submit():
            with self._db() as db:
                latest=db.execute('SELECT * FROM intent_trades WHERE id=?',(tid,)).fetchone()
            if latest['data']!=row['data']: return False
            try:
                current=self.load_settings()
            except (ValueError,TypeError,ArithmeticError,KeyError):
                refusal['reason']='invalid_local_settings'
                return False
            if snapshot:
                try:
                    pinned=self.policy_for(tid,e,account)
                    if pinned!=snapshot or (side=='buy' and pinned['entry_closed']): return False
                    if plan:
                        with self._db() as db:
                            saved=db.execute('SELECT data FROM intent_policy_plan WHERE event_id=?',(e['event_id'],)).fetchone()
                        if not saved or json.loads(saved[0])!=plan: return False
                except (ValueError,KeyError,TypeError): return False
            if any(current[key]!=settings[key] for key in ('mode','max_slippage_bps','max_slippage_amount')):
                refusal['reason']='pricing_changed'
                return False
            if side=='buy':
                try:
                    sample=self.entry_clock.read()
                    current_time=datetime.fromtimestamp(sample.effective,timezone.utc)
                    start_time=datetime.fromtimestamp(sample.wall,timezone.utc)
                except ClockUncertain:
                    refusal['reason']='clock_changed'
                    return False
                created=datetime.fromisoformat(e['created_at'].replace('Z','+00:00'))
                expires=datetime.fromisoformat(e['expires_at'].replace('Z','+00:00'))
                if latest['invalid'] or latest['skipped']: refusal['reason']='invalidated'
                elif not current['enabled']: refusal['reason']='entries_paused'
                elif start_time<created: refusal['reason']='future_created_at'
                elif current_time>=expires: refusal['reason']='expired'
                elif (current_time-created).total_seconds()>current['max_age_seconds']: refusal['reason']='max_age'
                elif e['quantity']>current['max_quantity']: refusal['reason']='max_quantity'
                else: return True
                return False
            return True
        self._trace(tid,'broker_submit_started',e['event_id'],client_order_id=cid,side=side,quantity=str(qty),order_type=request['type'],limit_price=request.get('limit_price'))
        try:
            if hasattr(self.broker,'submit_intent_checked'):
                self.broker.submit_intent_checked(request,can_submit,event=e,trade_id=tid,ordinal=len(revision_exits) if side=='sell' else 0)
            elif hasattr(self.broker,'submit_checked'):
                self.broker.submit_checked(request, can_submit)
            elif not snapshot:
                if not can_submit(): raise BrokerSuperseded('Instruction changed')
                self.broker.submit(request)
            else: raise BrokerNotSubmitted('Checked policy submission unavailable')
        except BrokerSuperseded:
            self._trace(tid,'broker_submit_superseded',e['event_id'],client_order_id=cid,reason=refusal['reason'])
            with self._db() as db: db.execute("UPDATE intent_orders SET status='skipped' WHERE cid=?",(cid,))
            return {'trade_id':tid,'state':'superseded'}
        except BrokerNotSubmitted:
            self._trace(tid,'broker_submit_rejected',e['event_id'],client_order_id=cid)
            with self._db() as db: db.execute("UPDATE intent_orders SET status='rejected' WHERE cid=?",(cid,))
            return self._settle(tid,e,'manual_reconcile' if side=='sell' else 'rejected')
        self._trace(tid,'broker_submit_returned',e['event_id'],client_order_id=cid)
        self._reconcile(next(o for o in self._orders(tid) if o['cid']==cid))
        if next(o for o in self._orders(tid) if o['cid']==cid)['status']=='rejected': return self._settle(tid,e,'manual_reconcile' if side=='sell' else 'rejected')
        return {'trade_id':tid,'state':'submitted'}
