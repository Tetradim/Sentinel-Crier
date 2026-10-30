from datetime import datetime, timezone
from uuid import uuid4
import pytest
from crier.managed_account import ManagedAccount
from crier.allocation_bank import BankConflict
from crier.intent_broker import BrokerSuperseded, BrokerNotSubmitted
from test_allocation_bank import setup_bank, SCOPE, SYMBOL


class Broker:
    account=SCOPE.account
    environment=SCOPE.environment
    def __init__(self):
        self.rows={}; self.posts=0; self.timeout=False; self.positions={}
    def verify(self, environment):
        assert environment==self.environment
        return self.account
    def metadata(self, event):
        return dict(account=self.account,environment=self.environment,symbol=SYMBOL,
                    asset='option',currency='USD',multiplier=100)
    def allocation_funds(self):
        return dict(account=self.account,environment=self.environment,currency='USD',
                    cash='1000',equity='10000',observed_at=datetime.now(timezone.utc))
    def allocation_positions(self): return self.positions
    def lookup(self,cid): return self.rows.get(cid)
    def cancel(self,broker_id):
        row=next(row for row in self.rows.values() if row['id']==broker_id)
        row['status']='canceled'
    def submit_checked(self,request,can_submit):
        if not can_submit(): raise BrokerSuperseded('Changed')
        self.posts+=1
        if self.timeout: raise TimeoutError('Unknown outcome')
        row=dict(request,id='broker-'+request['client_order_id'],status='new',
                 filled_qty='0',filled_avg_price=None)
        self.rows[request['client_order_id']]=row
        return row


def request(managed):
    event=dict(event_id=str(uuid4()),trade_id=str(uuid4()),symbol=SYMBOL,asset='option')
    cid=managed.make_order_id(event,'buy',0)
    order=dict(symbol=SYMBOL,asset='option',qty='3',side='buy',type='limit',
               limit_price='0.20',client_order_id=cid)
    return event,order


def test_reservation_precedes_post_and_repeat_never_posts(tmp_path):
    bank=setup_bank(tmp_path); broker=Broker(); managed=ManagedAccount(bank,SCOPE,'alice',broker)
    event,order=request(managed)
    managed.submit_intent_checked(order,lambda:True,event=event,trade_id=event['trade_id'],ordinal=0)
    assert bank.account(SCOPE)['available']=='940'
    managed.submit_intent_checked(order,lambda:True,event=event,trade_id=event['trade_id'],ordinal=0)
    assert broker.posts==1


def test_timeout_survives_restart_and_does_not_retry_post(tmp_path):
    bank=setup_bank(tmp_path); broker=Broker(); broker.timeout=True
    managed=ManagedAccount(bank,SCOPE,'alice',broker); event,order=request(managed)
    with pytest.raises(TimeoutError):
        managed.submit_intent_checked(order,lambda:True,event=event,trade_id=event['trade_id'],ordinal=0)
    managed=ManagedAccount(bank,SCOPE,'alice',broker)
    with pytest.raises(BankConflict):
        managed.submit_intent_checked(order,lambda:True,event=event,trade_id=event['trade_id'],ordinal=0)
    assert broker.posts==1
    assert bank.account(SCOPE)['available']=='940'


def test_last_moment_supersession_releases_definite_no_post(tmp_path):
    bank=setup_bank(tmp_path); broker=Broker(); managed=ManagedAccount(bank,SCOPE,'alice',broker)
    event,order=request(managed)
    with pytest.raises(BrokerSuperseded):
        managed.submit_intent_checked(order,lambda:False,event=event,trade_id=event['trade_id'],ordinal=0)
    assert broker.posts==0
    assert bank.account(SCOPE)['available']=='1000'


def test_stale_funds_cannot_authorize_order(tmp_path):
    bank=setup_bank(tmp_path); broker=Broker(); managed=ManagedAccount(bank,SCOPE,'alice',broker)
    original=broker.allocation_funds
    broker.allocation_funds=lambda:dict(original(),observed_at=datetime(2020,1,1,tzinfo=timezone.utc))
    event,order=request(managed)
    with pytest.raises(BrokerNotSubmitted):
        managed.submit_intent_checked(order,lambda:True,event=event,trade_id=event['trade_id'],ordinal=0)
    assert broker.posts==0


def test_two_real_engines_share_one_account_without_sharing_owned_units(tmp_path):
    from crier.intent_engine import IntentEngine
    from test_intent_engine import event
    bank=setup_bank(tmp_path); broker=Broker()
    broker.position=lambda symbol:sum(broker.positions.values())
    engines=[]
    for route,quantity in [('alice',3),('dave',5)]:
        managed=ManagedAccount(bank,SCOPE,route,broker)
        engine=IntentEngine(tmp_path/(route+'.db'),managed)
        engine.save_settings({'enabled':True})
        entry=event(symbol=SYMBOL,asset='option',quantity=quantity,limit_price='0.20')
        engine.accept(entry); engine.tick()
        cid=managed.make_order_id(entry,'buy',0)
        assert cid in broker.rows
        broker.rows[cid].update(status='filled',filled_qty=str(quantity),filled_avg_price='0.20')
        broker.positions[SYMBOL]=broker.positions.get(SYMBOL,0)+quantity
        engine.tick()
        engines.append((engine,entry))
    engine,entry=engines[0]
    exit=event('exit',2,trade_id=entry['trade_id'],symbol=SYMBOL,asset='option',quantity=3,limit_price='0.22')
    engine.accept(exit);engine.tick()
    sells=[row for row in broker.rows.values() if row['side']=='sell']
    assert len(sells)==1 and sells[0]['qty']=='3'
    sells[0].update(status='filled',filled_qty='3',filled_avg_price='0.22')
    broker.positions[SYMBOL]=5
    engine.tick()
    assert [(lot['route'],lot['units']) for lot in bank.active(SCOPE)]==[('dave',5)]


def test_cancel_and_zero_pool_preserve_partial_fill_exit_authority(tmp_path):
    from crier.intent_engine import IntentEngine
    from test_intent_engine import event
    bank=setup_bank(tmp_path);broker=Broker()
    broker.position=lambda symbol:broker.positions.get(symbol,0)
    managed=ManagedAccount(bank,SCOPE,'alice',broker)
    engine=IntentEngine(tmp_path/'alice.db',managed);engine.save_settings({'enabled':True})
    entry=event(symbol=SYMBOL,asset='option',quantity=5,limit_price='0.20')
    engine.accept(entry);engine.tick()
    cid=managed.make_order_id(entry,'buy',0)
    broker.rows[cid].update(status='partially_filled',filled_qty='2',filled_avg_price='0.20')
    broker.positions[SYMBOL]=2
    cancel=event('cancel',2,trade_id=entry['trade_id'],symbol=SYMBOL,asset='option',quantity=5,limit_price='0.20')
    engine.accept(cancel);engine.tick();engine.tick()
    assert bank.active(SCOPE)[0]['units']==2
    assert bank.account(SCOPE)['available']=='960'
    bank.configure(SCOPE,'alice','option',dict(mode='dollars',value='0'))
    exit=event('exit',3,trade_id=entry['trade_id'],symbol=SYMBOL,asset='option',quantity=2,limit_price='0.20')
    engine.accept(exit);engine.tick()
    sell=next(row for row in broker.rows.values() if row['side']=='sell')
    sell.update(status='filled',filled_qty='2',filled_avg_price='0.20')
    broker.positions[SYMBOL]=0
    engine.tick()
    assert bank.active(SCOPE)==[]
    assert bank.account(SCOPE)['available']=='1000'
