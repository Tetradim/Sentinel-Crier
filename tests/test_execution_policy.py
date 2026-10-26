from decimal import Decimal
import pytest
from crier.execution_policy import ExecutionPolicy, entry_target, source_exit_fraction
from test_intent_engine import event, Broker
from crier.intent_engine import IntentEngine


class PlannedBroker(Broker):
    def metadata(self, instruction):
        return dict(account='test-account', environment='paper', symbol=instruction['symbol'],
                    asset=instruction['asset'], currency='USD', multiplier=100 if instruction['asset']=='option' else 1)

    def submit_checked(self, order, can_submit):
        from crier.intent_broker import BrokerSuperseded
        binding=order.get('_policy_metadata')
        if binding is not None and binding != self.metadata(order | {'environment':'paper'}):
            raise BrokerSuperseded('Metadata changed')
        if not can_submit():
            raise BrokerSuperseded('Changed')
        return self.submit({k:v for k,v in order.items() if not k.startswith('_')})


def configured(tmp_path, policy, **kwargs):
    broker=PlannedBroker()
    engine=IntentEngine(tmp_path/'policy.db',broker,pairing_id='pair-hash',role='follower',**kwargs)
    engine.save_settings({'execution_policy':policy})
    engine.save_settings({'enabled':True})
    return engine,broker


def test_snapshot_before_settings_edit_and_frozen_target(tmp_path):
    engine,broker=configured(tmp_path,{'mode':'fixed','fixed_quantity':3})
    instruction=event()
    engine.accept(instruction)
    engine.save_settings({'enabled':False,'execution_policy':{'mode':'fixed','fixed_quantity':7}})
    engine.save_settings({'enabled':True})
    assert engine.tick()[0]['state']=='submitted'
    assert broker.sent[0]['qty']=='3'
    assert engine.status()['policies'][instruction['trade_id']]['policy']['fixed_quantity']==3


def test_proportional_exit_uses_actual_buys_and_cumulative_source_intents(tmp_path):
    engine,broker=configured(tmp_path,{'mode':'fixed','fixed_quantity':5,'exit_mode':'proportional'})
    instruction=event(quantity=10)
    engine.accept(instruction); engine.tick()
    next(iter(broker.orders.values())).update(status='filled',filled_qty='5',filled_avg_price='10')
    engine.accept(event('exit',2,instruction['trade_id'],quantity=4)); engine.tick()
    assert broker.sent[-1]['qty']=='2'
    next(reversed(broker.orders.values())).update(status='filled',filled_qty='2',filled_avg_price='11')
    engine.accept(event('exit',3,instruction['trade_id'],quantity=6)); engine.tick()
    assert broker.sent[-1]['qty']=='3'


def test_policy_save_must_pause_and_host_cannot_select(tmp_path):
    engine,broker=configured(tmp_path,{})
    with pytest.raises(ValueError): engine.save_settings({'execution_policy':{'mode':'fixed','fixed_quantity':2}})
    host=IntentEngine(tmp_path/'host.db',broker,pairing_id='host',role='host')
    with pytest.raises(ValueError): host.save_settings({'execution_policy':{}})


def test_timeout_cancels_only_acknowledged_buy_and_never_reopens(tmp_path):
    clock=[100.0]
    engine,broker=configured(tmp_path,{'entry_timeout_seconds':2},monotonic=lambda:clock[0])
    instruction=event(); engine.accept(instruction); engine.tick()
    clock[0]+=3
    assert engine.tick()[0]['state']=='cancel_pending'
    assert next(iter(broker.orders.values()))['status']=='canceled'
    engine.accept(event('replace',2,instruction['trade_id']))
    engine.tick(); assert len(broker.sent)==1


def test_reference_budget_option_math():
    policy=ExecutionPolicy.parse({'mode':'budget','budget':'100'})
    instruction=event(asset='option')
    assert entry_target(policy,instruction,'0.20',{'multiplier':100})==5
    assert entry_target(policy,instruction,'0.40',{'multiplier':100},2,Decimal('30'))==3


def test_history_gap_and_duplicate_sequence_fail():
    first=event(); last=event('exit',3,first['trade_id'])
    with pytest.raises(ValueError): source_exit_fraction([first,last],last)
    last=event('exit',2,first['trade_id'])
    assert source_exit_fraction([first,last],last)==(10,10)
    with pytest.raises(ValueError): source_exit_fraction([first,last,last],last)


def test_unknown_submit_restart_never_duplicates_and_timer_starts_on_ack(tmp_path):
    engine,broker=configured(tmp_path,{'entry_timeout_seconds':30})
    instruction=event(); broker.timeout=True
    engine.accept(instruction); engine.tick()
    # No lookup occurred after the ambiguous POST. Restart discovers it and starts a new verified anchor.
    engine=IntentEngine(engine.path,broker,pairing_id='pair-hash',role='follower')
    assert engine.tick()[0]['state']=='working'
    assert len(broker.sent)==1
    # A second restart now has persisted acknowledged evidence: cancel after fresh lookup.
    engine=IntentEngine(engine.path,broker,pairing_id='pair-hash',role='follower')
    assert engine.tick()[0]['state']=='cancel_pending'
    assert len(broker.sent)==1


def test_missing_prior_ack_evidence_never_renews_timer(tmp_path):
    engine,broker=configured(tmp_path,{'entry_timeout_seconds':30})
    engine.accept(event()); engine.tick()
    with engine._db() as db: db.execute('DELETE FROM intent_policy_evidence')
    engine=IntentEngine(engine.path,broker,pairing_id='pair-hash',role='follower')
    assert engine.tick()[0]['state']=='cancel_pending'
    assert len(broker.sent)==1


def test_missing_metadata_or_checked_adapter_cannot_post(tmp_path):
    engine,broker=configured(tmp_path,{'mode':'fixed','fixed_quantity':2})
    broker.metadata=lambda _:dict(currency='USD',multiplier=1)
    engine.accept(event()); assert engine.tick()[0]['state']=='reconcile_required'
    assert not broker.sent and not engine.status()['orders']


def test_receipt_policy_is_not_reinterpreted_by_new_setting(tmp_path):
    broker=PlannedBroker(); engine=IntentEngine(tmp_path/'legacy.db',broker,pairing_id='pair-hash',role='follower')
    engine.save_settings({'enabled':True}); instruction=event(); engine.accept(instruction)
    engine.save_settings({'enabled':False,'execution_policy':{'mode':'fixed','fixed_quantity':2}})
    engine.save_settings({'enabled':True}); engine.tick()
    assert broker.sent[0]['qty']=='10'


def test_missing_current_snapshot_fails_closed_not_legacy(tmp_path):
    engine,broker=configured(tmp_path,{})
    instruction=event(); engine.accept(instruction)
    with engine._db() as db: db.execute('DELETE FROM intent_policy_trade')
    engine=IntentEngine(engine.path,broker,pairing_id='pair-hash',role='follower')
    assert engine.tick()[0]['state']=='reconcile_required'; assert not broker.sent


def test_legacy_schema_migration_explicitly_preserves_old_trade(tmp_path):
    engine,broker=configured(tmp_path,{})
    instruction=event(); engine.accept(instruction)
    with engine._db() as db:
        for table in ('intent_policy_schema','intent_policy_trade','intent_policy_plan','intent_policy_evidence','intent_event_index'):
            db.execute('DROP TABLE '+table)
    engine=IntentEngine(engine.path,broker,pairing_id='pair-hash',role='follower')
    assert engine.status()['policies'][instruction['trade_id']]=={'legacy':True}


def test_missing_schema_marker_with_advanced_records_cannot_downgrade(tmp_path):
    engine,broker=configured(tmp_path,{'mode':'fixed','fixed_quantity':2})
    engine.accept(event())
    with engine._db() as db: db.execute('DELETE FROM intent_policy_schema')
    with pytest.raises(ValueError,match='schema marker'):
        IntentEngine(engine.path,broker,pairing_id='pair-hash',role='follower')
    assert not broker.sent


@pytest.mark.parametrize('target',[1001,4,True,'3',-1])
def test_corrupted_saved_plan_cannot_increase_submission(tmp_path,target):
    import json
    engine,broker=configured(tmp_path,{'mode':'fixed','fixed_quantity':3,'max_local_quantity':5})
    instruction=event(); engine.accept(instruction)
    original=engine.policy_plan
    def interrupted(*args,**kwargs):
        result=original(*args,**kwargs)
        raise RuntimeError('Crash after plan before reservation')
    engine.policy_plan=interrupted
    engine.tick(); assert not engine.status()['orders']
    with engine._db() as db:
        row=db.execute('SELECT data FROM intent_policy_plan').fetchone()
        plan=json.loads(row[0]); plan['target']=target
        db.execute('UPDATE intent_policy_plan SET data=?',(json.dumps(plan),))
    engine=IntentEngine(engine.path,broker,pairing_id='pair-hash',role='follower')
    assert engine.tick()[0]['state']=='reconcile_required'
    assert not broker.sent


def test_corrupted_positive_price_cannot_change_frozen_limit(tmp_path):
    import json
    engine,broker=configured(tmp_path,{'mode':'fixed','fixed_quantity':3})
    engine.accept(event())
    original=engine.policy_plan
    def interrupted(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('Crash before reservation')
    engine.policy_plan=interrupted; engine.tick()
    with engine._db() as db:
        plan=json.loads(db.execute('SELECT data FROM intent_policy_plan').fetchone()[0])
        plan['limit_price']='100.00'
        db.execute('UPDATE intent_policy_plan SET data=?',(json.dumps(plan),))
    engine=IntentEngine(engine.path,broker,pairing_id='pair-hash',role='follower')
    assert engine.tick()[0]['state']=='reconcile_required'
    assert not broker.sent


def test_missing_prior_buy_plan_blocks_replacement_but_allows_exit(tmp_path):
    engine,broker=configured(tmp_path,{'mode':'fixed','fixed_quantity':3})
    instruction=event(); engine.accept(instruction); engine.tick()
    next(iter(broker.orders.values())).update(status='filled',filled_qty='3',filled_avg_price='10')
    with engine._db() as db: db.execute('DELETE FROM intent_policy_plan')
    engine.accept(event('replace',2,instruction['trade_id']))
    assert engine.tick()[0]['state']=='reconcile_required'; assert len(broker.sent)==1
    engine.accept(event('exit',3,instruction['trade_id'],quantity=3)); engine.tick()
    assert broker.sent[-1]['side']=='sell' and broker.sent[-1]['qty']=='3'


def test_corrupt_saved_enabled_flag_cannot_bypass_final_pause_gate(tmp_path):
    import json
    engine,broker=configured(tmp_path,{'mode':'fixed','fixed_quantity':3})
    engine.accept(event())
    original=broker.submit_checked
    def corrupt(request,check):
        with engine._db() as db:
            settings=json.loads(db.execute('SELECT data FROM intent_settings').fetchone()[0])
            settings['enabled']='false'
            db.execute('UPDATE intent_settings SET data=?',(json.dumps(settings),))
        return original(request,check)
    broker.submit_checked=corrupt
    assert engine.tick()[0]['state']=='superseded'
    assert not broker.sent
    with engine._db() as db: assert db.execute('SELECT status FROM intent_orders').fetchone()[0]=='skipped'


def test_close_tracked_exit_ignores_requested_units_but_bounds_holdings(tmp_path):
    engine,broker=configured(tmp_path,{'mode':'fixed','fixed_quantity':5,'exit_mode':'close_tracked'})
    instruction=event(); engine.accept(instruction); engine.tick()
    next(iter(broker.orders.values())).update(status='filled',filled_qty='5',filled_avg_price='10')
    broker.available=3
    engine.accept(event('exit',2,instruction['trade_id'],quantity=1)); engine.tick()
    assert broker.sent[-1]['qty']=='3'


def test_proportional_history_gap_cancels_working_buy_before_blocking_exit(tmp_path):
    engine,broker=configured(tmp_path,{'exit_mode':'proportional'})
    instruction=event(); engine.accept(instruction); engine.tick()
    next(iter(broker.orders.values())).update(filled_qty='3',filled_avg_price='10')
    engine.accept(event('exit',3,instruction['trade_id'],quantity=10))
    assert engine.tick()[0]['state']=='cancel_pending'
    assert engine.tick()[0]['state']=='reconcile_required'
    assert len(broker.sent)==1


def test_replace_budget_uses_actual_spend_and_never_recycles_sales(tmp_path):
    engine,broker=configured(tmp_path,{'mode':'budget','budget':'100'})
    instruction=event(limit_price='10'); engine.accept(instruction); engine.tick()
    next(iter(broker.orders.values())).update(status='canceled',filled_qty='3',filled_avg_price='9')
    replacement=event('replace',2,instruction['trade_id'],limit_price='20')
    engine.accept(replacement); engine.tick()
    assert broker.sent[-1]['qty']=='3'  # 73 unspent / 20, plus three already bought.
    assert engine.status()['plans'][replacement['event_id']]['target']==6


def test_missing_cumulative_cost_blocks_budget_replace_but_not_exit(tmp_path):
    engine,broker=configured(tmp_path,{'mode':'budget','budget':'100'})
    instruction=event(); engine.accept(instruction); engine.tick()
    next(iter(broker.orders.values())).update(status='canceled',filled_qty='3')
    engine.accept(event('replace',2,instruction['trade_id']))
    assert engine.tick()[0]['state']=='reconcile_required'; assert len(broker.sent)==1
    engine.accept(event('exit',3,instruction['trade_id'],quantity=3)); engine.tick()
    assert broker.sent[-1]['side']=='sell' and broker.sent[-1]['qty']=='3'


def test_final_pause_refuses_planned_order_as_known_not_sent(tmp_path):
    engine,broker=configured(tmp_path,{'mode':'fixed','fixed_quantity':2})
    original=broker.submit_checked
    def pause(request,check):
        engine.save_settings({'enabled':False})
        return original(request,check)
    broker.submit_checked=pause
    engine.accept(event()); assert engine.tick()[0]['state']=='superseded'
    assert not broker.sent and engine.status()['orders'][0]['status']=='skipped'


@pytest.mark.parametrize('changes',[{'version':True},{'ratio_bps':3},{'mode':'budget','budget':'1e3'},
                                    {'entry_timeout_seconds':True},{'entry_timeout_seconds':0},{'extra':1}])
def test_strict_runtime_policy(changes):
    with pytest.raises(ValueError): ExecutionPolicy.parse(changes)
