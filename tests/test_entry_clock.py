import math
import pytest
from datetime import datetime, timezone
from crier.entry_clock import EntryClock, ClockUncertain
from crier.intent_engine import IntentEngine
from crier.intent_broker import BrokerSuperseded
from test_intent_engine import Broker, event


def test_small_backward_slew_cannot_extend_the_entry_window():
    wall=[1000.0]; mono=[10.0]; clock=EntryClock(lambda:wall[0],lambda:mono[0])
    wall[0]+=1; mono[0]+=3
    assert clock.now()==1003
    wall[0]=1002; mono[0]=14
    assert clock.now()==1004


@pytest.mark.parametrize('wall,mono',[(1060,11),(940,11),(1000,9),(math.nan,11),(1000,math.inf)])
def test_clock_discontinuities_and_invalid_samples_are_uncertain(wall,mono):
    values=[1000.0,10.0]; clock=EntryClock(lambda:values[0],lambda:values[1]); values[:]=[wall,mono]
    with pytest.raises(ClockUncertain): clock.now()


def test_clock_change_defers_new_entry_without_poisoning_a_later_valid_check(tmp_path):
    values=[datetime.now(timezone.utc).timestamp(),100.0]
    clock=EntryClock(lambda:values[0],lambda:values[1]); broker=Broker()
    engine=IntentEngine(tmp_path/'orders.db',broker,entry_clock=clock); engine.save_settings({'enabled':True})
    instruction=event(created_at=datetime.fromtimestamp(values[0]-1,timezone.utc).isoformat()); engine.accept(instruction); values[0]+=60
    assert engine.tick()[0]['state']=='waiting_for_clock'
    assert not broker.sent and not engine.status()['trades'][0]['skipped']
    values[0]-=60
    assert engine.tick()[0]['state']=='submitted'


def test_backward_slew_does_not_start_a_future_instruction_early(tmp_path):
    base=datetime.now(timezone.utc).timestamp(); values=[base,100.0]
    clock=EntryClock(lambda:values[0],lambda:values[1]); broker=Broker()
    engine=IntentEngine(tmp_path/'orders.db',broker,entry_clock=clock); engine.save_settings({'enabled':True})
    instruction=event(created_at=datetime.fromtimestamp(base+0.5,timezone.utc).isoformat(),expires_at=datetime.fromtimestamp(base+20,timezone.utc).isoformat())
    engine.accept(instruction); values[0]-=1; values[1]+=1
    assert engine.tick()[0]['state']=='waiting_for_start'; assert not broker.sent


def test_clock_change_inside_preflight_is_known_not_submitted(tmp_path):
    values=[datetime.now(timezone.utc).timestamp(),100.0]; broker=Broker()
    clock=EntryClock(lambda:values[0],lambda:values[1])
    def checked(order,allowed):
        values[0]-=60
        if not allowed(): raise BrokerSuperseded('Local final check refused')
        broker.submit(order)
    broker.submit_checked=checked
    engine=IntentEngine(tmp_path/'orders.db',broker,entry_clock=clock); engine.save_settings({'enabled':True})
    instruction=event(created_at=datetime.fromtimestamp(values[0]-1,timezone.utc).isoformat()); engine.accept(instruction)
    assert engine.tick()[0]['state']=='superseded'; assert not broker.sent
    assert any(r['details'].get('reason')=='clock_changed' for r in engine.trade_trace(instruction['trade_id']))


def test_entry_clock_uncertainty_does_not_block_an_exit(tmp_path):
    broker=Broker(); clock=EntryClock(); engine=IntentEngine(tmp_path/'orders.db',broker,entry_clock=clock)
    engine.save_settings({'enabled':True}); buy=event(); engine.accept(buy); engine.tick()
    broker.orders[broker.sent[0]['client_order_id']].update(status='filled',filled_qty='10')
    clock.read=lambda: (_ for _ in ()).throw(ClockUncertain())
    engine.accept(event('exit',2,buy['trade_id'])); assert engine.tick()[0]['state']=='submitted'
    assert broker.sent[-1]['side']=='sell'


def test_pricing_change_during_preflight_never_sends_the_old_price(tmp_path):
    broker=Broker(); engine=IntentEngine(tmp_path/'orders.db',broker); engine.save_settings({'enabled':True})
    def checked(order,allowed):
        engine.save_settings({'mode':'bounded_limit','max_slippage_amount':'0.01'})
        if not allowed(): raise BrokerSuperseded('Pricing changed before dispatch')
        broker.submit(order)
    broker.submit_checked=checked; instruction=event(); engine.accept(instruction)
    assert engine.tick()[0]['state']=='superseded'; assert not broker.sent
    assert any(r['details'].get('reason')=='pricing_changed' for r in engine.trade_trace(instruction['trade_id']))
