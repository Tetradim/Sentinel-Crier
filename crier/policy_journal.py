"""Transactional policy evidence, independent of broker network calls."""
from dataclasses import asdict
from decimal import Decimal
import json
import math
from .execution_policy import ExecutionPolicy, validate_metadata, entry_target, source_exit_fraction, final_limit, exact_cost


class PolicyJournal:
    def migrate_policies(self, db):
        existing={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'intent_policy_%'")}
        db.executescript('''
        CREATE TABLE IF NOT EXISTS intent_policy_schema(id INTEGER PRIMARY KEY, version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS intent_policy_trade(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS intent_policy_plan(event_id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS intent_policy_evidence(cid TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS intent_event_index(id TEXT PRIMARY KEY, trade_id TEXT NOT NULL, sequence INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS intent_event_trade ON intent_event_index(trade_id,sequence);
        ''')
        marker=db.execute('SELECT version FROM intent_policy_schema WHERE id=1').fetchone()
        if marker:
            if marker[0]!=1: raise ValueError('Unknown execution policy schema')
            return
        if existing:
            raise ValueError('Missing execution policy schema marker')
        db.execute('BEGIN IMMEDIATE')
        for row in db.execute('SELECT id FROM intent_trades').fetchall():
            db.execute('INSERT OR REPLACE INTO intent_policy_trade VALUES (?,?)',(row[0],json.dumps({'legacy':True})))
        for row in db.execute('SELECT id,data FROM intent_events').fetchall():
            event=json.loads(row[1])
            db.execute('INSERT OR REPLACE INTO intent_event_index VALUES (?,?,?)',(row[0],event['trade_id'],event['sequence']))
        db.execute('INSERT INTO intent_policy_schema VALUES (1,1)')

    def snapshot_policy(self, db, event, settings):
        selected=settings['execution_policy']
        if selected is None:
            value={'legacy':True}
        else:
            if self.role!='follower' or not self.pairing_id:
                raise ValueError('Follower pairing required for execution policy')
            policy=ExecutionPolicy.parse(selected)
            policy=ExecutionPolicy.parse(dict(asdict(policy),max_source_quantity=min(policy.max_source_quantity,settings['max_quantity'])))
            value=dict(legacy=False,policy=asdict(policy),pairing_id=self.pairing_id,role=self.role,
                       environment=event['environment'],symbol=event['symbol'],asset=event['asset'],account=None,entry_closed=False)
        db.execute('INSERT INTO intent_policy_trade VALUES (?,?)',(event['trade_id'],json.dumps(value,sort_keys=True)))

    def policy_for(self, tid, event=None, account=None):
        with self._db() as db:
            row=db.execute('SELECT data FROM intent_policy_trade WHERE id=?',(tid,)).fetchone()
            if not row: raise ValueError('Missing policy provenance')
            value=json.loads(row[0])
            if value.get('legacy') is True:
                if value!={'legacy':True}: raise ValueError('Contradictory legacy policy')
                return None
            if value.get('legacy') is not False: raise ValueError('Missing policy mode')
            ExecutionPolicy.parse(value['policy'])
            if value['pairing_id']!=self.pairing_id or value['role']!=self.role or self.role!='follower' or not self.pairing_id:
                raise ValueError('Policy pairing changed')
            if event and any(value[k]!=event[k] for k in ('environment','symbol','asset')):
                raise ValueError('Policy instrument changed')
            if account:
                if value['account'] not in (None,account): raise ValueError('Policy account changed')
                if value['account'] is None:
                    value['account']=account
                    db.execute('UPDATE intent_policy_trade SET data=? WHERE id=?',(json.dumps(value,sort_keys=True),tid))
            return value

    def reconcile_policy_evidence(self, db, order, snap):
        record=db.execute('SELECT data FROM intent_policy_evidence WHERE cid=?',(order['cid'],)).fetchone()
        evidence=json.loads(record[0]) if record else {}
        if not isinstance(evidence,dict): raise ValueError('Invalid policy order evidence')
        if 'ack_session' in evidence:
            anchor=evidence.get('ack_monotonic')
            if not isinstance(evidence['ack_session'],str) or not evidence['ack_session'] or type(anchor) not in (int,float) or not math.isfinite(anchor):
                raise ValueError('Invalid acknowledgement evidence')
        # An absent price invalidates cost evidence for this new cumulative fill.
        evidence['filled']=str(snap['filled_qty'])
        evidence['average']=str(snap['filled_avg_price']) if snap.get('filled_avg_price') is not None else None
        if snap['status'] not in ('pending_new','rejected') and snap['status'] not in self.policy_terminal:
            if 'ack_session' not in evidence:
                now=self.monotonic()
                if not math.isfinite(now): raise ValueError('Invalid monotonic clock')
                # Durable broker identity/live status proves this was already acknowledged.
                # Losing its timer evidence cannot grant it a fresh lifetime on restart.
                prior_ack=order['broker_id'] and order['status'] not in ('unknown','pending_new')
                evidence.update(ack_session='missing-prior-ack' if prior_ack else self.policy_session,ack_monotonic=now)
        db.execute('INSERT OR REPLACE INTO intent_policy_evidence VALUES (?,?)',(order['cid'],json.dumps(evidence,sort_keys=True)))

    def timed_entry_closed(self, tid, snapshot, orders):
        if not snapshot: return False
        seconds=snapshot['policy']['entry_timeout_seconds']
        if not seconds: return False
        closed=snapshot['entry_closed']
        now=self.monotonic()
        with self._db() as db:
            for order in orders:
                if order['side']!='buy' or order['status'] in self.policy_terminal: continue
                row=db.execute('SELECT data FROM intent_policy_evidence WHERE cid=?',(order['cid'],)).fetchone()
                evidence=json.loads(row[0]) if row else {}
                if 'ack_session' in evidence:
                    anchor=evidence['ack_monotonic']
                    closed=closed or evidence['ack_session']!=self.policy_session or not math.isfinite(now) or now<anchor or now-anchor>=seconds
            if closed and not snapshot['entry_closed']:
                snapshot['entry_closed']=True
                db.execute('UPDATE intent_policy_trade SET data=? WHERE id=?',(json.dumps(snapshot,sort_keys=True),tid))
        return closed

    def policy_spent(self, orders, multiplier):
        spent=Decimal(0)
        with self._db() as db:
            for order in orders:
                if order['side']!='buy' or Decimal(order['filled'])==0: continue
                row=db.execute('SELECT data FROM intent_policy_evidence WHERE cid=?',(order['cid'],)).fetchone()
                evidence=json.loads(row[0]) if row else {}
                if evidence.get('average') is None or Decimal(evidence.get('filled','-1'))!=Decimal(order['filled']):
                    raise ValueError('Cumulative buy cost unavailable')
                average=Decimal(evidence['average'])
                if not average.is_finite() or average<=0: raise ValueError('Invalid cumulative buy cost')
                filled_cost=exact_cost(Decimal(order['filled']),average,multiply=True)
                spent=exact_cost(spent,exact_cost(filled_cost,Decimal(multiplier),multiply=True))
        return spent

    def validate_saved_plan(self, plan, policy, snapshot, event, metadata, bought, spent):
        fields={'snapshot','event','metadata','target','limit_price','order_type','baseline_bought','baseline_spent','pricing'}
        if type(plan) is not dict or set(plan)!=fields or type(plan['target']) is not int or not 1<=plan['target']<=policy.max_local_quantity:
            raise ValueError('Invalid persisted policy target')
        baseline=plan['baseline_bought']
        if type(baseline) is not int or not 0<=baseline<=bought:
            raise ValueError('Invalid plan purchase baseline')
        if type(plan['baseline_spent']) is not str:
            raise ValueError('Invalid plan cost baseline')
        cost=Decimal(plan['baseline_spent'])
        if not cost.is_finite() or cost<0 or cost>spent:
            raise ValueError('Contradictory plan cost baseline')
        if plan['snapshot']!=dict(snapshot,entry_closed=False) or plan['event']!=event or plan['metadata']!=metadata:
            raise ValueError('Policy plan binding changed')
        if plan['order_type'] not in ('market','limit') or final_limit(event,plan['pricing'])!=plan['limit_price'] or (plan['order_type']=='market')!=(plan['pricing']['mode']=='market'):
            raise ValueError('Persisted limit does not match pricing basis')
        if entry_target(policy,event,plan['limit_price'],metadata,baseline,cost)!=plan['target']:
            raise ValueError('Persisted target does not match policy')

    def policy_plan(self, tid, event, snapshot, request, bought, orders, account, settings):
        policy=ExecutionPolicy.parse(snapshot['policy'])
        if not hasattr(self.broker,'metadata') or not hasattr(self.broker,'submit_checked'):
            raise ValueError('Checked policy broker unavailable')
        metadata=validate_metadata(self.broker.metadata(event),event,account)
        with self._db() as db:
            row=db.execute('SELECT data FROM intent_policy_plan WHERE event_id=?',(event['event_id'],)).fetchone()
        spent=self.policy_spent(orders,metadata['multiplier']) if policy.mode=='budget' or policy.max_entry_notional is not None else Decimal(0)
        with self._db() as db:
            for order in orders:
                if order['side']!='buy': continue
                prior=db.execute('SELECT e.data,p.data FROM intent_event_index i JOIN intent_events e ON e.id=i.id LEFT JOIN intent_policy_plan p ON p.event_id=e.id WHERE i.trade_id=? AND i.sequence=?',(tid,order['sequence'])).fetchall()
                if len(prior)!=1 or prior[0][1] is None: raise ValueError('Missing prior buy plan provenance')
                self.validate_saved_plan(json.loads(prior[0][1]),policy,snapshot,json.loads(prior[0][0]),metadata,bought,spent)
        if row:
            plan=json.loads(row[0])
            self.validate_saved_plan(plan,policy,snapshot,event,metadata,bought,spent)
            if plan['order_type']!=request['type']: raise ValueError('Order pricing type changed')
        else:
            target=entry_target(policy,event,request.get('limit_price'),metadata,bought,spent)
            pricing={k:settings[k] for k in ('mode','max_slippage_bps','max_slippage_amount')}
            plan=dict(snapshot=dict(snapshot,entry_closed=False),event=event,metadata=metadata,target=target,limit_price=request.get('limit_price'),order_type=request['type'],baseline_bought=int(bought),baseline_spent=format(spent,'f'),pricing=pricing)
            with self._db() as db:
                db.execute('INSERT INTO intent_policy_plan VALUES (?,?)',(event['event_id'],json.dumps(plan,sort_keys=True)))
        # Recheck remaining notional using actual cumulative costs on every resume.
        quantity=max(Decimal(0),Decimal(plan['target'])-bought)
        if request.get('limit_price')!=plan['limit_price']:
            request['limit_price']=plan['limit_price']
        for cap in (policy.budget if policy.mode=='budget' else None,policy.max_entry_notional):
            if cap is not None:
                reserved=exact_cost(quantity,Decimal(plan['limit_price']),multiply=True)
                projected=exact_cost(spent,exact_cost(reserved,Decimal(metadata['multiplier']),multiply=True))
                if projected>Decimal(cap): raise ValueError('Remaining entry cost exceeds policy')
        request['_policy_metadata']=metadata
        return quantity,plan

    def proportional_due(self, tid, desired, bought, sold):
        with self._db() as db:
            events=[json.loads(row[0]) for row in db.execute('SELECT e.data FROM intent_events e JOIN intent_event_index i ON e.id=i.id WHERE i.trade_id=? AND i.sequence<=?',(tid,desired['sequence']))]
        numerator,denominator=source_exit_fraction(events,desired)
        return max(Decimal(0),(bought*numerator//denominator)-sold)
