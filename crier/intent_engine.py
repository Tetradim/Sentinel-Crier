"""Durable intent executor. Receipt never waits on broker network operations."""
from datetime import datetime, timezone
from contextlib import contextmanager
from .intent_broker import BrokerNotSubmitted, BrokerSuperseded
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import json
import sqlite3
import threading
import time
from .intent_protocol import IntentEvent
from .trade_diagnostics import validate_quote, trade_report, export_trade_json, export_trade_csv
from .lock import single_process, AlreadyRunningError

DEFAULTS = dict(enabled=False, mode='exact_limit', max_slippage_bps=100,
                max_slippage_amount='0.02', max_age_seconds=10, max_quantity=1000)
TERMINAL = {'filled', 'canceled', 'expired', 'rejected', 'replaced', 'skipped'}
BROKER_STATUSES = {'new', 'accepted', 'pending_new', 'accepted_for_bidding',
                   'partially_filled', 'filled', 'done_for_day', 'canceled',
                   'expired', 'replaced', 'pending_cancel', 'pending_replace',
                   'stopped', 'rejected', 'suspended', 'calculated'}

class IntentEngine:
    def __init__(self, path, broker, clock=None):
        self.path, self.broker = str(path), broker
        self.clock = clock or time.time
        self.worker = threading.Lock()
        with self._db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS intent_events(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS intent_trades(id TEXT PRIMARY KEY, data TEXT NOT NULL, invalid INTEGER NOT NULL, skipped INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS intent_orders(cid TEXT PRIMARY KEY, trade_id TEXT, sequence INTEGER, side TEXT, qty TEXT, status TEXT, broker_id TEXT, filled TEXT);
            CREATE TABLE IF NOT EXISTS intent_settings(id INTEGER PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS intent_pin(id INTEGER PRIMARY KEY, environment TEXT, account TEXT);
            CREATE TABLE IF NOT EXISTS intent_cancel_requested(cid TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS intent_settled(id TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS intent_trace(id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, monotonic_ns INTEGER NOT NULL, trade_id TEXT NOT NULL, event_id TEXT, stage TEXT NOT NULL, details TEXT NOT NULL);''')
            if 'attempted_at' not in {r[1] for r in db.execute('PRAGMA table_info(intent_cancel_requested)')}:
                db.execute('ALTER TABLE intent_cancel_requested ADD COLUMN attempted_at REAL')
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
        return dict(DEFAULTS, **(json.loads(row[0]) if row else {}))
    def save_settings(self, settings):
        s=dict(self.load_settings(), **settings)
        if set(s)!=set(DEFAULTS) or type(s['enabled']) is not bool or s['mode'] not in {'exact_limit','market','bounded_limit'}: raise ValueError('Invalid intent settings')
        for key,lo,hi in [('max_age_seconds',1,30),('max_quantity',1,1000),('max_slippage_bps',0,10000)]:
            if type(s[key]) is not int or not lo<=s[key]<=hi: raise ValueError('Invalid '+key)
        amount=Decimal(str(s['max_slippage_amount']))
        if not amount.is_finite() or amount<0: raise ValueError('Invalid slippage')
        s['max_slippage_amount']=str(amount)
        with self._db() as db: db.execute('INSERT OR REPLACE INTO intent_settings VALUES (1,?)',(json.dumps(s),))
        return s
    def accept(self, event):
        e=IntentEvent.model_validate(event).to_dict() if isinstance(event,dict) else IntentEvent.model_validate(event.to_dict()).to_dict()
        encoded=json.dumps(e,sort_keys=True,default=lambda x:x.isoformat())
        e=json.loads(encoded); settings=self.load_settings()
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
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
            desired=encoded if not prior or e['sequence']>prior['sequence'] else row['data']
            db.execute('INSERT OR REPLACE INTO intent_trades VALUES (?,?,?,?)',(e['trade_id'],desired,invalid,skipped))
        self._trace(e['trade_id'],'instruction_stored',e['event_id'],action=e['action'],sequence=e['sequence'],symbol=e['symbol'],asset=e['asset'],quantity=e['quantity'],limit_price=e['limit_price'],sender_created_at=e['created_at'],expires_at=e['expires_at'])
        return {'state':'stored','trade_id':e['trade_id']}
    def status(self):
        with self._db() as db:
            trades=[dict(id=r['id'], event=json.loads(r['data']), invalid=bool(r['invalid']), skipped=bool(r['skipped'])) for r in db.execute('SELECT * FROM intent_trades')]
            orders=[dict(r) for r in db.execute('SELECT * FROM intent_orders')]
            pin=db.execute('SELECT environment,account FROM intent_pin WHERE id=1').fetchone()
        return {'settings':self.load_settings(),'trades':trades,'orders':orders,'pin':dict(pin) if pin else None}
    def _orders(self, tid):
        with self._db() as db: return [dict(r) for r in db.execute('SELECT * FROM intent_orders WHERE trade_id=?',(tid,))]
    def _reconcile(self, order):
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
                    self._trace(tid,'execution_error',error_type=type(exc).__name__)
                    results.append({'trade_id':tid,'state':'reconcile_required','error':type(exc).__name__})
        finally: self.worker.release()
        return results
    def _settle(self, tid, event, state):
        with self._db() as db:
            current=db.execute('SELECT data FROM intent_trades WHERE id=?',(tid,)).fetchone()[0]
            if json.loads(current)==event:
                db.execute('INSERT OR REPLACE INTO intent_settled VALUES (?,?)',(tid,current))
        self._trace(tid,'execution_decision',event.get('event_id'),state=state)
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
        reconciled={order['cid'] for order in self._orders(tid) if self._reconcile(order)}
        orders=self._orders(tid); active=[o for o in orders if o['status'] not in TERMINAL]
        cancel=[o for o in active if o['side']=='buy' and (row['invalid'] or row['skipped'] or o['sequence']!=e['sequence'])]
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
            return {'trade_id':tid,'state':'cancel_pending'}
        if active: return {'trade_id':tid,'state':'working'}
        settings=self.load_settings(); action=e['action']; side='sell' if action=='exit' else 'buy'
        if action=='cancel' or (side=='buy' and (row['invalid'] or row['skipped'])): return self._settle(tid,e,'invalidated')
        now=datetime.now(timezone.utc)
        if side=='buy' and now<datetime.fromisoformat(e['created_at'].replace('Z','+00:00')):
            # A future-dated event is not permanently invalid: wait for its
            # validity window. Later revisions must remain eligible.
            self._trace(tid,'execution_deferred',e['event_id'],reason='future_created_at',sender_created_at=e['created_at'])
            return {'trade_id':tid,'state':'waiting_for_start'}
        if side=='buy' and (not settings['enabled'] or now>=datetime.fromisoformat(e['expires_at'].replace('Z','+00:00')) or (now-datetime.fromisoformat(e['created_at'].replace('Z','+00:00'))).total_seconds()>settings['max_age_seconds'] or e['quantity']>settings['max_quantity']):
            with self._db() as db: db.execute('UPDATE intent_trades SET skipped=1 WHERE id=?',(tid,))
            return self._settle(tid,e,'skipped')
        bought=sum((Decimal(o['filled']) for o in orders if o['side']=='buy'),Decimal(0))
        sold=sum((Decimal(o['filled']) for o in orders if o['side']=='sell'),Decimal(0))
        revision_exits=[o for o in orders if o['side']=='sell' and o['sequence']==e['sequence']]
        revision_sold=sum((Decimal(o['filled']) for o in revision_exits),Decimal(0))
        if side=='sell':
            if any(o['status']!='filled' for o in revision_exits):
                return self._settle(tid,e,'manual_reconcile')
            remaining=min(Decimal(e['quantity'])-revision_sold,bought-sold)
            if remaining<=0: return self._settle(tid,e,'settled')
            available=Decimal(str(self.broker.position(e['symbol'])))
            if not available.is_finite(): raise ValueError('Invalid available holdings')
            qty=min(remaining,max(Decimal(0),available))
        else:
            qty=Decimal(e['quantity'])-bought
        qty=qty.to_integral_value(rounding=ROUND_DOWN)
        cid='si-'+e['event_id']+('-s'+str(len(revision_exits)) if side=='sell' else '-b')
        if side=='sell' and qty<=0: return {'trade_id':tid,'state':'waiting_for_availability'}
        if any(o['cid']==cid and o['status']=='rejected' for o in orders): return self._settle(tid,e,'rejected')
        if qty<=0 or any(o['cid']==cid for o in orders): return self._settle(tid,e,'settled')
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
        # Atomic reservation against the newest desired state. Release DB before network.
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            newest=db.execute('SELECT * FROM intent_trades WHERE id=?',(tid,)).fetchone()
            if newest['data']!=row['data'] or (side=='buy' and (newest['invalid'] or newest['skipped'])): return {'trade_id':tid,'state':'superseded'}
            db.execute('INSERT INTO intent_orders VALUES (?,?,?,?,?,?,?,?)',(cid,tid,e['sequence'],side,str(qty),'unknown',None,'0'))
        def can_submit():
            with self._db() as db:
                latest=db.execute('SELECT * FROM intent_trades WHERE id=?',(tid,)).fetchone()
            if latest['data']!=row['data']: return False
            if side=='buy':
                current=self.load_settings()
                current_time=datetime.now(timezone.utc)
                created=datetime.fromisoformat(e['created_at'].replace('Z','+00:00'))
                expires=datetime.fromisoformat(e['expires_at'].replace('Z','+00:00'))
                return not latest['invalid'] and not latest['skipped'] and current['enabled'] and created<=current_time<expires and (current_time-created).total_seconds()<=current['max_age_seconds'] and e['quantity']<=current['max_quantity']
            return True
        self._trace(tid,'broker_submit_started',e['event_id'],client_order_id=cid,side=side,quantity=str(qty),order_type=request['type'],limit_price=request.get('limit_price'))
        try:
            if hasattr(self.broker,'submit_checked'):
                self.broker.submit_checked(request, can_submit)
            else:
                if not can_submit(): raise BrokerSuperseded('Instruction changed')
                self.broker.submit(request)
        except BrokerSuperseded:
            self._trace(tid,'broker_submit_superseded',e['event_id'],client_order_id=cid)
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
