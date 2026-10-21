from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from crier.intent_engine import IntentEngine

class Broker:
    def __init__(self):
        self.orders = {}; self.sent = []; self.available = 100; self.timeout = False; self.on_submit = None
    def verify(self, environment):
        if environment != 'paper': raise ValueError('environment mismatch')
        return 'test-account'
    def lookup(self, cid): return self.orders.get(cid)
    def submit(self, order):
        self.sent.append(order)
        row = dict(order, id=order['client_order_id'], status='new', filled_qty='0')
        self.orders[row['id']] = row
        if self.on_submit: self.on_submit()
        if self.timeout: raise TimeoutError()
        return row
    def cancel(self, oid): self.orders[oid]['status'] = 'canceled'
    def position(self, symbol): return self.available

def event(action='enter', sequence=1, trade_id=None, **changes):
    now = datetime.now(timezone.utc)
    result = dict(version=1,event_id=str(uuid4()),trade_id=trade_id or str(uuid4()),sequence=sequence,action=action,environment='paper',symbol='AAPL',asset='stock',quantity=10,limit_price='10.00',created_at=now.isoformat(),expires_at=(now+timedelta(seconds=20)).isoformat())
    result.update(changes); return result

@pytest.fixture
def pair(tmp_path):
    b=Broker(); e=IntentEngine(tmp_path/'intent.db', b); e.save_settings({'enabled':True}); return e,b

def test_cancel_before_enter(pair):
    e,b=pair; x=event('cancel',2); e.accept(x); e.accept(event(trade_id=x['trade_id'])); e.tick(); assert not b.sent

def test_duplicate_and_timeout_never_resubmit(pair):
    e,b=pair; x=event(); b.timeout=True; e.accept(x); e.tick(); e.accept(x); e.tick(); e.tick(); assert len(b.sent)==1

def test_exit_waits_for_cancel_fill_race(pair):
    e,b=pair; x=event(); e.accept(x); e.tick(); row=next(iter(b.orders.values())); row['filled_qty']='4'
    e.accept(event('exit',2,x['trade_id'])); e.tick(); row['filled_qty']='6'; e.tick()
    assert b.sent[-1]['side']=='sell'; assert b.sent[-1]['qty']=='6'

def test_cancel_during_submit(pair):
    e,b=pair; x=event(); b.on_submit=lambda:e.accept(event('cancel',2,x['trade_id'])); e.accept(x); e.tick(); e.tick(); assert next(iter(b.orders.values()))['status']=='canceled'

def test_paused_is_permanent(pair):
    e,b=pair; e.save_settings({'enabled':False}); e.accept(event()); e.save_settings({'enabled':True}); e.tick(); assert not b.sent

def test_expired_and_environment(pair):
    e,b=pair; e.accept(event(created_at=(datetime.now(timezone.utc)-timedelta(seconds=21)).isoformat(),expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())); e.tick(); assert not b.sent
    e.accept(event(environment='live')); e.tick(); assert not b.sent

def test_exit_before_fill_and_unrelated_holdings(pair):
    e,b=pair; x=event('exit',2); e.accept(x); e.accept(event(trade_id=x['trade_id'])); e.tick(); assert not b.sent

def test_replace_only_remaining_target(pair):
    e,b=pair; x=event(); e.accept(x); e.tick(); row=next(iter(b.orders.values())); row['filled_qty']='4'
    e.accept(event('replace',2,x['trade_id'],quantity=12)); e.tick(); e.tick()
    assert len(b.sent)==2 and b.sent[-1]['qty']=='8'

def test_bounded_price_and_holdings_cap(pair):
    e,b=pair; e.save_settings({'mode':'bounded_limit'}); x=event(); e.accept(x); e.tick(); assert b.sent[0]['limit_price']=='10.02'
    row=next(iter(b.orders.values())); row.update(status='filled',filled_qty='10'); b.available=3
    e.accept(event('exit',2,x['trade_id'])); e.tick(); assert b.sent[-1]['qty']=='3'; assert b.sent[-1]['limit_price']=='9.98'

def test_account_pin_survives_restart(pair):
    e,b=pair; b.verify=lambda env:'account-one'; e.accept(event()); e.tick()
    b.verify=lambda env:'account-two'; other=IntentEngine(e.path,b); other.accept(event()); other.tick(); assert len(b.sent)==1

def test_broker_account_environment_checks():
    import httpx
    from crier.intent_broker import AlpacaIntentBroker
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json={'id':'wrong','status':'ACTIVE'})
    b=AlpacaIntentBroker('paper','key','secret','expected',httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(ValueError): b.verify('live')
    assert not calls
    with pytest.raises(ValueError): b.verify('paper')
    assert len(calls)==1

def test_unknown_absent_survives_restart(pair):
    e,b=pair; x=event(); b.timeout=True; e.accept(x); e.tick(); b.orders.clear(); e=IntentEngine(e.path,b); e.tick(); e.tick(); assert len(b.sent)==1

def test_cancel_is_requested_once(pair):
    e,b=pair; calls=[]; x=event(); e.accept(x); e.tick(); b.cancel=lambda oid:calls.append(oid)
    e.accept(event('cancel',2,x['trade_id'])); e.tick(); e.tick(); assert len(calls)==1

def test_failed_cancel_is_retried_after_reconciliation(pair):
    e,b=pair
    x=event()
    e.accept(x)
    e.tick()
    attempts=[]
    original=b.cancel
    def flaky_cancel(oid):
        attempts.append(oid)
        if len(attempts)==1:
            raise TimeoutError('cancel outcome uncertain')
        original(oid)
    b.cancel=flaky_cancel
    e.accept(event('cancel',2,x['trade_id']))
    assert e.tick()[0]['state']=='reconcile_required'
    assert next(iter(b.orders.values()))['status']=='new'
    assert e.tick()[0]['state']=='cancel_pending'
    assert len(attempts)==2
    assert next(iter(b.orders.values()))['status']=='canceled'
    e.tick()
    assert len(attempts)==2


def test_ambiguous_cancel_that_succeeded_does_not_repeat(pair):
    e,b=pair
    x=event()
    e.accept(x)
    e.tick()
    attempts=[]
    original=b.cancel
    def cancel_then_timeout(oid):
        attempts.append(oid)
        original(oid)
        raise TimeoutError('response lost after broker accepted cancel')
    b.cancel=cancel_then_timeout
    e.accept(event('cancel',2,x['trade_id']))
    assert e.tick()[0]['state']=='reconcile_required'
    e.tick()
    assert len(attempts)==1
    assert next(iter(b.orders.values()))['status']=='canceled'


def test_broker_order_identity_mismatch(pair):
    e,b=pair; x=event(); e.accept(x); e.tick(); row=next(iter(b.orders.values())); row.update(symbol='MSFT',status='filled',filled_qty='10')
    e.accept(event('exit',2,x['trade_id'])); result=e.tick(); assert result[0]['state']=='reconcile_required'; assert len(b.sent)==1

def test_definite_preflight_rejection(pair):
    from crier.intent_broker import BrokerNotSubmitted
    e,b=pair
    def reject(order): raise BrokerNotSubmitted('Contract unavailable')
    b.submit=reject; e.accept(event()); result=e.tick(); assert result[0]['state']=='rejected'; assert e.status()['orders'][0]['status']=='rejected'

def test_subdollar_option_price_uses_cent_tick(pair):
    e,b=pair; e.save_settings({'mode':'bounded_limit'}); e.accept(event(asset='option',symbol='AAPL261218C00300000',limit_price='0.50')); e.tick(); assert b.sent[0]['limit_price']=='0.50'

def test_settled_trades_do_not_poll_forever(pair):
    e,b=pair; e.accept(event()); e.tick(); row=next(iter(b.orders.values())); row.update(status='filled',filled_qty='10'); e.tick()
    calls=[]; b.verify=lambda env:calls.append(env); assert e.tick()==[]; assert not calls

def test_adapter_option_contract_and_preflight_rejection():
    import httpx
    from crier.intent_broker import AlpacaIntentBroker, BrokerNotSubmitted
    paths=[]
    def handler(request):
        paths.append(request.url.path)
        if request.url.path=='/v2/account': return httpx.Response(200,json={'id':'pinned','status':'ACTIVE'})
        return httpx.Response(200,json={'symbol':'AAPL261218C00300000','tradable':False,'status':'inactive','size':'100'})
    b=AlpacaIntentBroker('paper','key','secret','pinned',httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(BrokerNotSubmitted): b.submit({'symbol':'AAPL261218C00300000','asset':'option','side':'buy'})
    assert paths==['/v2/account','/v2/options/contracts/AAPL261218C00300000']

def test_adapter_missing_available_position_fails_closed():
    import httpx
    from crier.intent_broker import AlpacaIntentBroker
    b=AlpacaIntentBroker('paper','key','secret','pinned',httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'symbol':'AAPL','qty':'100'}))))
    with pytest.raises(ValueError): b.position('AAPL')

def test_broker_rejected_snapshot_is_reported(pair):
    e,b=pair
    original=b.submit
    def reject(order):
        row=original(order); row['status']='rejected'; return row
    b.submit=reject; e.accept(event()); assert e.tick()[0]['state']=='rejected'

def test_exit_waits_for_available_then_finishes_remaining(pair):
    e,b=pair; x=event(); e.accept(x); e.tick(); row=next(iter(b.orders.values())); row.update(status='filled',filled_qty='10')
    b.available=0; e.accept(event('exit',2,x['trade_id'],quantity=5)); assert e.tick()[0]['state']=='waiting_for_availability'
    b.available=2; e.tick(); first=b.sent[-1]; assert first['qty']=='2'; b.orders[first['client_order_id']].update(status='filled',filled_qty='2')
    b.available=8; e.tick(); second=b.sent[-1]; assert second['qty']=='3'; assert second['client_order_id']!=first['client_order_id']
    b.orders[second['client_order_id']].update(status='filled',filled_qty='3'); assert e.tick()[0]['state']=='settled'; assert len(b.sent)==3

def test_canceled_exit_needs_manual_reconciliation(pair):
    e,b=pair; x=event(); e.accept(x); e.tick(); next(iter(b.orders.values())).update(status='filled',filled_qty='10')
    e.accept(event('exit',2,x['trade_id'],quantity=5)); e.tick(); row=b.orders[b.sent[-1]['client_order_id']]; row.update(status='canceled',filled_qty='2')
    assert e.tick()[0]['state']=='manual_reconcile'; e.tick(); assert len(b.sent)==2

def test_future_entry_is_skipped(pair):
    e,b=pair; now=datetime.now(timezone.utc); e.accept(event(created_at=(now+timedelta(seconds=5)).isoformat(),expires_at=(now+timedelta(seconds=25)).isoformat())); e.tick(); assert not b.sent

def test_cancel_arriving_during_adapter_preflight_blocks_post(tmp_path):
    import httpx
    from crier.intent_broker import AlpacaIntentBroker
    x=event(); calls=[]; account_calls=0
    def handler(request):
        nonlocal account_calls
        calls.append(request.method+' '+request.url.path)
        if request.url.path=='/v2/account':
            account_calls+=1
            if account_calls==2: engine.accept(event('cancel',2,x['trade_id']))
            return httpx.Response(200,json={'id':'pinned','status':'ACTIVE'})
        if request.url.path.startswith('/v2/assets/'):
            return httpx.Response(200,json={'symbol':'AAPL','class':'us_equity','tradable':True,'status':'active'})
        if request.url.path=='/v2/orders:by_client_order_id': return httpx.Response(404,json={})
        return httpx.Response(200,json={})
    broker=AlpacaIntentBroker('paper','key','secret','pinned',httpx.Client(transport=httpx.MockTransport(handler)))
    engine=IntentEngine(tmp_path/'checked.db',broker); engine.save_settings({'enabled':True}); engine.accept(x)
    assert engine.tick()[0]['state']=='superseded'; assert not any(c.startswith('POST') for c in calls)
    engine.tick(); assert engine.status()['orders'][0]['status']=='skipped'

def test_shared_crossplatform_client_ids(pair):
    e,b=pair; x=event(); e.accept(x); e.tick(); assert b.sent[-1]['client_order_id']=='si-'+x['event_id']+'-b'
    next(iter(b.orders.values())).update(status='filled',filled_qty='10')
    close=event('exit',2,x['trade_id'],quantity=5); b.available=2; e.accept(close); e.tick()
    first=b.sent[-1]; assert first['client_order_id']=='si-'+close['event_id']+'-s0'
    b.orders[first['client_order_id']].update(status='filled',filled_qty='2'); b.available=8; e.tick()
    assert b.sent[-1]['client_order_id']=='si-'+close['event_id']+'-s1'

def test_duplicate_422_is_not_definite_rejection():
    import httpx
    from crier.intent_broker import AlpacaIntentBroker
    def handler(request):
        if request.url.path=='/v2/account': return httpx.Response(200,json={'id':'pinned','status':'ACTIVE'})
        if request.url.path.startswith('/v2/assets/'):
            return httpx.Response(200,json={'symbol':'AAPL','class':'us_equity','tradable':True,'status':'active'})
        return httpx.Response(422,json={'message':'client_order_id must be unique'})
    broker=AlpacaIntentBroker('paper','key','secret','pinned',httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(httpx.HTTPStatusError): broker.submit({'symbol':'AAPL','asset':'stock','side':'buy'})


def test_explicit_422_invalid_quantity_is_definitive_rejection():
    import httpx
    from crier.intent_broker import AlpacaIntentBroker, BrokerNotSubmitted
    def handler(request):
        if request.url.path=='/v2/account':
            return httpx.Response(200,json={'id':'pinned','status':'ACTIVE'})
        if request.url.path.startswith('/v2/assets/'):
            return httpx.Response(200,json={'symbol':'AAPL','class':'us_equity','tradable':True,'status':'active'})
        return httpx.Response(422,json={'message':'invalid qty'})
    broker=AlpacaIntentBroker('paper','key','secret','pinned',httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(BrokerNotSubmitted):
        broker.submit({'symbol':'AAPL','asset':'stock','side':'buy'})


def test_unknown_422_remains_ambiguous():
    import httpx
    from crier.intent_broker import AlpacaIntentBroker
    def handler(request):
        if request.url.path=='/v2/account':
            return httpx.Response(200,json={'id':'pinned','status':'ACTIVE'})
        if request.url.path.startswith('/v2/assets/'):
            return httpx.Response(200,json={'symbol':'AAPL','class':'us_equity','tradable':True,'status':'active'})
        return httpx.Response(422,json={'message':'order rejected'})
    broker=AlpacaIntentBroker('paper','key','secret','pinned',httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(httpx.HTTPStatusError):
        broker.submit({'symbol':'AAPL','asset':'stock','side':'buy'})


def test_future_entry_waits_without_permanent_skip(pair):
    e,b=pair
    now=datetime.now(timezone.utc)
    x=event(created_at=(now+timedelta(seconds=5)).isoformat(),
            expires_at=(now+timedelta(seconds=25)).isoformat())
    e.accept(x)
    assert e.tick()[0]['state']=='waiting_for_start'
    assert not e.status()['trades'][0]['skipped']
    assert not b.sent


def test_future_entry_does_not_poison_later_revision(pair):
    e,b=pair
    now=datetime.now(timezone.utc)
    x=event(created_at=(now+timedelta(seconds=5)).isoformat(),
            expires_at=(now+timedelta(seconds=25)).isoformat())
    e.accept(x)
    e.tick()
    replacement=event('replace',2,x['trade_id'])
    e.accept(replacement)
    assert e.tick()[0]['state']=='submitted'
    assert len(b.sent)==1
