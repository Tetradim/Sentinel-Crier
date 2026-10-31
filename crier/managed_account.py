"""Opt-in account-bank dispatch boundary. Installation/migration is separate.

The caller must supply an already verified, pinned broker. No credentials live
in this object or its ledger. An ambiguous POST is never repeated here.
"""
from datetime import datetime, timezone
from decimal import Decimal
import json
import sqlite3
from pathlib import Path

from .allocation_bank import BankConflict, TERMINAL
from .intent_broker import BrokerNotSubmitted, BrokerSuperseded


def verify_legacy_journal(path, broker, scope, bank=None, route=None, undispatched=None):
    """Read-only migration: never adopt unresolved orders or old open lots."""
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        pin=db.execute('SELECT environment,account FROM intent_pin WHERE id=1').fetchone()
        orders=db.execute('SELECT * FROM intent_orders').fetchall()
        trades={row[0]:json.loads(row[1]) for row in db.execute('SELECT id,data FROM intent_trades')}
    if pin and tuple(pin)!=(scope.environment,scope.account):
        raise BankConflict('Retained journal account mismatch')
    owned={}
    for order in orders:
        if order['status'] in ('rejected','skipped') and not order['broker_id'] and Decimal(order['filled'])==0:
            continue
        if order['cid'].startswith('sc-'):
            registered=bank.order(scope,order['cid']) if bank else None
            if not registered and order['cid']==undispatched and not order['broker_id'] and Decimal(order['filled'])==0:
                continue
            if not registered or (route is not None and bank.history(scope,registered['bank_id'])['route']!=route):
                raise BankConflict('Managed order evidence is missing from the ID bank')
            continue
        proof=broker.lookup(order['cid'])
        trade=trades[order['trade_id']]
        if not proof or (proof.get('client_order_id'),proof.get('symbol'),proof.get('side'))!=(
                order['cid'],trade['symbol'],order['side']):
            raise BankConflict('Legacy order needs recovery before account-bank setup')
        filled=Decimal(str(proof.get('filled_qty')))
        if (proof.get('status') not in TERMINAL or not proof.get('id') or
                Decimal(str(proof.get('qty')))!=Decimal(order['qty']) or not filled.is_finite() or
                filled!=filled.to_integral_value() or not Decimal(order['filled'])<=filled<=Decimal(order['qty']) or
                (order['broker_id'] and order['broker_id']!=proof['id'])):
            raise BankConflict('Legacy order is unresolved; preserve its original route')
        owned[order['trade_id']]=owned.get(order['trade_id'],Decimal(0))+filled*(1 if order['side']=='buy' else -1)
    if any(owned.values()):
        raise BankConflict('Close and reconcile existing Crier lots before enabling the shared bank')


class ManagedAccount:
    def __init__(self, bank, scope, route, broker):
        if (broker.account, broker.environment) != (scope.account, scope.environment):
            raise BankConflict('Managed broker identity mismatch')
        self.bank, self.scope, self.route, self.broker = bank, scope, route, broker
        self.account, self.environment = scope.account, scope.environment
        self.legacy_cids=set()

    def make_order_id(self, event, side, ordinal):
        return self.bank.client_id(self.scope, self.route, event['trade_id'],
                                   event['event_id'], side, ordinal)

    def attach_journal(self, path, pairing):
        verify_legacy_journal(path,self.broker,self.scope,self.bank,self.route)
        with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
            self.legacy_cids.update(row[0] for row in db.execute('SELECT cid FROM intent_orders') if not row[0].startswith('sc-'))
        self.bank.register_journal(self.scope,self.route,path,pairing)

    def observe_intent(self, event):
        if event['action'] in ('cancel','exit'):
            self.bank.invalidate(self.scope,self.route,event['trade_id'],event['action'])

    def settled_intent(self,event,state):
        if state in ('invalidated','rejected','skipped'):
            self.bank.invalidate(self.scope,self.route,event['trade_id'],state)
        elif state=='settled':
            for row in self.bank.active(self.scope,self.route):
                if row['trade']==event['trade_id'] and not any(row[name] for name in ('units','pending_buy_units','pending_exit_units')):
                    self.bank.retire(self.scope,self.route,event['trade_id'],'settled_empty')

    def lookup(self, cid):
        with self.bank.locked(self.scope):
            row = self.bank.order(self.scope, cid)
            if row is None:
                if cid in self.legacy_cids: return self.broker.lookup(cid)
                raise BankConflict('Order is not registered in this account bank')
            snapshot = self.broker.lookup(cid)
            if snapshot is not None:
                self.bank.observe(self.scope, cid, snapshot)
            return snapshot

    def _reconcile(self, undispatched=None):
        for path in self.bank.journals(self.scope):
            verify_legacy_journal(path,self.broker,self.scope,self.bank,undispatched=undispatched)
        for row in self.bank.orders(self.scope):
            if row['status'] in TERMINAL:
                continue
            snapshot = self.broker.lookup(row['cid'])
            if snapshot is None:
                raise BankConflict('Unresolved order outcome; reservation retained')
            self.bank.observe(self.scope, row['cid'], snapshot)
        self.bank.inventory(self.scope, self.broker.allocation_positions())

    def _funds(self):
        funds = self.broker.allocation_funds()
        if (funds.get('account'), funds.get('environment'), funds.get('currency')) != (
                self.account, self.environment, 'USD'):
            raise BankConflict('Fresh USD funds for the pinned account required')
        observed = funds.get('observed_at')
        if not isinstance(observed, datetime) or observed.utcoffset() is None:
            raise BankConflict('Timestamped account funds required')
        age = (datetime.now(timezone.utc) - observed).total_seconds()
        if not 0 <= age <= 10:
            raise BankConflict('Stale account funds cannot authorize an order')
        return funds

    def recovery_check(self):
        from .recovery_assistant import recovery_report
        result='verified'
        with self.bank.locked(self.scope):
            self.broker.verify(self.environment)
            try:
                self._reconcile()
            except BankConflict:
                result='unresolved'
            positions=self.broker.allocation_positions()
            try: self.bank.inventory(self.scope,positions)
            except BankConflict: result='unresolved'
            from .allocation_bank import scope_key
            with self.bank.db() as db:
                baseline={row[0]:row[1] for row in db.execute('SELECT symbol,quantity FROM bank_baselines WHERE scope=?',(scope_key(self.scope),))}
            owned={}
            for row in self.bank.active(self.scope):
                owned[row['symbol']]=owned.get(row['symbol'],0)+row['units']
            comparison=[dict(symbol=symbol,host_owned=owned.get(symbol,0),external_baseline=baseline.get(symbol,0),
                expected=owned.get(symbol,0)+baseline.get(symbol,0),broker=positions.get(symbol,0),
                difference=positions.get(symbol,0)-owned.get(symbol,0)-baseline.get(symbol,0))
                for symbol in sorted(set(positions)|set(baseline)|set(owned))]
            if any(row['difference'] for row in comparison): result='unresolved'
        report=recovery_report(self.bank,self.scope)
        from datetime import datetime,timezone
        report.update(broker_checked=result=='verified',check_result=result,positions=comparison,
                      positions_checked_at=datetime.now(timezone.utc).isoformat())
        return report

    def submit_intent_checked(self, request, can_submit, *, event, trade_id, ordinal):
        try:
            return self._submit(request,can_submit,event=event,trade_id=trade_id,ordinal=ordinal)
        except BankConflict as exc:
            if self.bank.order(self.scope,request.get('client_order_id','')) is None:
                raise BrokerNotSubmitted('Account bank refused an undispatched order') from exc
            raise

    def _submit(self, request, can_submit, *, event, trade_id, ordinal):
        with self.bank.locked(self.scope):
            if trade_id != event['trade_id'] or request['client_order_id'] != self.make_order_id(event, request['side'], ordinal):
                raise BankConflict('Immutable event and account order identity required')
            if request.get('type') != 'limit' or any(request.get(k) != event.get(k) for k in ('symbol', 'asset')):
                raise BrokerNotSubmitted('Managed orders require the exact instrument and a bounded limit')
            try:
                quantity = Decimal(request['qty'])
            except (ValueError,ArithmeticError) as exc:
                raise BrokerNotSubmitted('Invalid managed quantity') from exc
            if not quantity.is_finite() or quantity != quantity.to_integral_value() or quantity <= 0:
                raise BrokerNotSubmitted('Managed orders require positive whole units')
            self.broker.verify(self.environment)
            self._reconcile(request['client_order_id'])
            metadata = self.broker.metadata(dict(event, environment=self.environment))
            if any(metadata.get(k) != v for k, v in dict(account=self.account, environment=self.environment,
                    symbol=event['symbol'], asset=event['asset'], currency='USD',
                    multiplier=100 if event['asset']=='option' else 1).items()):
                raise BrokerNotSubmitted('Managed instrument metadata mismatch')
            funds = self._funds()
            self.bank.rebase_if_flat(self.scope,funds['cash'],funds['equity'])
            row = self.bank.reserve(self.scope, self.route, trade_id, event['event_id'],
                request['client_order_id'], request['symbol'], request['asset'], metadata['multiplier'],
                request['side'], int(quantity), request['limit_price'],
                self.bank.fee(self.scope, self.route, request['asset']),
                cash=funds['cash'], equity=funds['equity'], ordinal=ordinal)
            if row['existing']:
                # A prior invocation may already have dispatched. Even a 404 is
                # insufficient evidence to submit it again after a timeout.
                return None
            self.bank.mark_dispatching(self.scope, row['cid'])
            def fresh_instruction():
                age=(datetime.now(timezone.utc)-funds['observed_at']).total_seconds()
                return 0<=age<=10 and can_submit()
            try:
                result = self.broker.submit_checked(request, fresh_instruction)
            except (BrokerNotSubmitted, BrokerSuperseded):
                self.bank.not_submitted(self.scope, row['cid'], definitive=True)
                raise
            # All other exceptions retain the unknown order and its cash/units.
            if result is not None:
                self.bank.observe(self.scope, row['cid'], result)
            return result

    def submit_checked(self, request, can_submit):
        raise BrokerNotSubmitted('Managed execution requires explicit source-event context')

    def cancel(self, broker_order_id):
        with self.bank.locked(self.scope):
            owned = [row for row in self.bank.orders(self.scope)
                     if row['broker_id'] == broker_order_id and
                     self.bank.history(self.scope, row['bank_id'])['route'] == self.route]
            if len(owned) != 1:
                raise BankConflict('Cancellation is not owned by this host route')
            return self.broker.cancel(broker_order_id)

    def verify(self, environment): return self.broker.verify(environment)
    @property
    def client(self): return self.broker.client
    def metadata(self, event): return self.broker.metadata(event)
    def position(self, symbol): return self.broker.position(symbol)
    def close(self): return self.broker.close()
