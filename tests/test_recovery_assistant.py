from crier.recovery_assistant import recovery_report
from test_allocation_bank import setup_bank,reserve,SCOPE,SYMBOL


def test_unknown_order_report_preserves_reservations(tmp_path):
    bank=setup_bank(tmp_path);reserve(bank)
    before=bank.account(SCOPE)
    report=recovery_report(bank,SCOPE)
    assert report['state']=='needs_reconciliation'
    assert report['unknown_orders']==1
    assert report['can_clear'] is False
    assert bank.account(SCOPE)==before
    assert 'resubmit' in report['explanation'].lower()


def test_flat_report_does_not_claim_broker_verification(tmp_path):
    report=recovery_report(setup_bank(tmp_path),SCOPE)
    assert report['state']=='no_local_conflict'
    assert report['broker_checked'] is False


def test_fresh_check_reconciles_without_submitting(tmp_path):
    from crier.managed_account import ManagedAccount
    from test_managed_account import Broker
    bank=setup_bank(tmp_path);bank.inventory(SCOPE,{});broker=Broker()
    managed=ManagedAccount(bank,SCOPE,'alice',broker)
    report=managed.recovery_check()
    assert report['broker_checked'] is True
    assert broker.posts==0
    assert report['can_clear'] is False


def test_missing_options_capacity_does_not_block_stock_funds_or_flat_repair(tmp_path):
    from crier.managed_account import ManagedAccount
    from test_managed_account import Broker
    bank=setup_bank(tmp_path);bank.inventory(SCOPE,{})
    bank.block(SCOPE,'capacity_deficit')
    broker=Broker();original=broker.allocation_funds
    broker.allocation_funds=lambda:dict(original(),options_cash=None)
    assert ManagedAccount(bank,SCOPE,'alice',broker).repair_flat_account()['check_result']=='verified'


def test_option_entry_requires_its_own_capacity_without_changing_common_cash(tmp_path):
    import pytest
    from crier.managed_account import ManagedAccount
    from crier.intent_broker import BrokerNotSubmitted
    from test_managed_account import Broker,request
    bank=setup_bank(tmp_path);broker=Broker();original=broker.allocation_funds
    broker.allocation_funds=lambda:dict(original(),options_cash='0')
    managed=ManagedAccount(bank,SCOPE,'alice',broker);event,order=request(managed)
    with pytest.raises(BrokerNotSubmitted):managed.submit_intent_checked(order,lambda:True,event=event,trade_id=event['trade_id'],ordinal=0)
    assert broker.posts==0
    assert bank.account(SCOPE)['available']=='1000'


def test_unknown_check_retains_cash_and_reports_unresolved(tmp_path):
    from crier.managed_account import ManagedAccount
    from test_managed_account import Broker
    bank=setup_bank(tmp_path);reserve(bank);before=bank.account(SCOPE)
    broker=Broker();report=ManagedAccount(bank,SCOPE,'alice',broker).recovery_check()
    assert report['check_result']=='unresolved'
    assert bank.account(SCOPE)==before
    assert broker.posts==0


def test_comparison_includes_external_baseline_without_claiming_host_ownership(tmp_path):
    from crier.managed_account import ManagedAccount
    from test_managed_account import Broker
    bank=setup_bank(tmp_path);bank.inventory(SCOPE,{SYMBOL:10})
    broker=Broker();broker.positions={SYMBOL:9}
    report=ManagedAccount(bank,SCOPE,'alice',broker).recovery_check()
    assert report['positions']==[dict(symbol=SYMBOL,host_owned=0,external_baseline=10,expected=10,broker=9,difference=-1)]
    assert report['check_result']=='unresolved'
    assert broker.posts==0


def test_matching_inventory_cannot_present_evidence_block_as_resolved(tmp_path):
    from crier.managed_account import ManagedAccount
    from test_managed_account import Broker
    bank=setup_bank(tmp_path);bank.block(SCOPE,'broker_evidence_conflict')
    report=ManagedAccount(bank,SCOPE,'alice',Broker()).recovery_check()
    assert report['check_result']=='unresolved'
    assert report['state']=='needs_reconciliation'


def test_recovery_discovers_late_fill_for_retired_id(tmp_path):
    from crier.managed_account import ManagedAccount
    from test_managed_account import Broker
    from test_allocation_bank import proof
    bank=setup_bank(tmp_path);order=reserve(bank)
    bank.invalidate(SCOPE,'alice',order['trade'],'canceled')
    bank.observe(SCOPE,order['cid'],proof(order,0,'canceled'))
    broker=Broker();broker.rows[order['cid']]=proof(order,3)
    broker.positions={SYMBOL:3}
    report=ManagedAccount(bank,SCOPE,'alice',broker).recovery_check()
    assert bank.active(SCOPE)[0]['units']==3
    assert report['check_result']=='unresolved'


def test_flat_repair_caps_cash_and_preserves_tombstones(tmp_path):
    from crier.managed_account import ManagedAccount
    from test_managed_account import Broker
    from test_allocation_bank import proof
    bank=setup_bank(tmp_path);bank.inventory(SCOPE,{})
    order=reserve(bank);bank.invalidate(SCOPE,'alice',order['trade'],'canceled')
    bank.observe(SCOPE,order['cid'],proof(order,0,'canceled'))
    bank.block(SCOPE,'capacity_deficit')
    broker=Broker()
    broker.rows[order['cid']]=proof(order,0,'canceled')
    original=broker.allocation_funds
    broker.allocation_funds=lambda:dict(original(),cash='125',equity='100')
    report=ManagedAccount(bank,SCOPE,'alice',broker).repair_flat_account()
    assert report['check_result']=='verified'
    assert bank.account(SCOPE)['blocked']==''
    assert bank.account(SCOPE)['available']=='100'
    assert bank.history(SCOPE,order['bank_id'])['state']=='closed'
    assert broker.posts==0


def test_repair_cannot_initialize_or_replace_external_baseline(tmp_path):
    import pytest
    from crier.managed_account import ManagedAccount
    from crier.allocation_bank import BankConflict
    from test_managed_account import Broker
    bank=setup_bank(tmp_path);bank.block(SCOPE,'capacity_deficit')
    broker=Broker();broker.positions={SYMBOL:10}
    with pytest.raises(BankConflict):ManagedAccount(bank,SCOPE,'alice',broker).repair_flat_account()
    assert bank.account(SCOPE)['blocked']=='capacity_deficit'


def test_repair_refuses_missing_original_order_even_when_positions_flat(tmp_path):
    import pytest
    from crier.managed_account import ManagedAccount
    from crier.allocation_bank import BankConflict
    from test_managed_account import Broker
    bank=setup_bank(tmp_path);reserve(bank)
    before=bank.account(SCOPE)
    with pytest.raises(BankConflict):ManagedAccount(bank,SCOPE,'alice',Broker()).repair_flat_account()
    assert bank.account(SCOPE)==before


def test_definite_local_no_post_does_not_require_invented_broker_order(tmp_path):
    from crier.managed_account import ManagedAccount
    from test_managed_account import Broker
    bank=setup_bank(tmp_path);bank.inventory(SCOPE,{});order=reserve(bank);bank.not_submitted(SCOPE,order['cid'])
    broker=Broker()
    def refuse_lookup(cid):raise AssertionError('Synthetic no-post must not be broker queried')
    broker.lookup=refuse_lookup
    report=ManagedAccount(bank,SCOPE,'alice',broker).recovery_check()
    assert report['orders'][0]['result']=='definite_no_submission'
    assert report['check_result']=='verified'


def test_recovery_check_cannot_prime_missing_baseline_for_repair(tmp_path):
    import pytest
    from crier.managed_account import ManagedAccount
    from crier.allocation_bank import BankConflict,scope_key
    from test_managed_account import Broker
    bank=setup_bank(tmp_path);bank.block(SCOPE,'capacity_deficit')
    broker=Broker();broker.positions={SYMBOL:10}
    managed=ManagedAccount(bank,SCOPE,'alice',broker)
    managed.recovery_check()
    with bank.db() as db:
        assert db.execute('SELECT 1 FROM bank_inventory_initialized WHERE scope=?',(scope_key(SCOPE),)).fetchone() is None
    with pytest.raises(BankConflict):managed.repair_flat_account()


def test_repair_refuses_held_contracts_and_sweep_continues_after_missing_order(tmp_path):
    import pytest
    from crier.managed_account import ManagedAccount
    from crier.allocation_bank import BankConflict
    from test_managed_account import Broker
    from test_allocation_bank import proof
    bank=setup_bank(tmp_path);bank.inventory(SCOPE,{});reserve(bank);second=reserve(bank,route='dave')
    broker=Broker();broker.rows[second['cid']]=proof(second,3);broker.positions={SYMBOL:3}
    managed=ManagedAccount(bank,SCOPE,'alice',broker)
    report=managed.recovery_check()
    assert bank.active(SCOPE,'dave')[0]['units']==3
    assert {row['result'] for row in report['orders']}=={'verified','not_returned_unresolved'}
    with pytest.raises(BankConflict):managed.repair_flat_account()
    assert bank.active(SCOPE,'dave')[0]['units']==3
    assert broker.posts==0


def test_late_fill_deficit_requires_flat_repair_with_authoritative_cash(tmp_path):
    import pytest
    from crier.managed_account import ManagedAccount
    from crier.allocation_bank import BankConflict
    from test_managed_account import Broker
    from test_allocation_bank import proof
    bank=setup_bank(tmp_path,cash='60');bank.inventory(SCOPE,{})
    first=reserve(bank);bank.observe(SCOPE,first['cid'],proof(first,0,'canceled'))
    second=reserve(bank,route='dave')
    bank.observe(SCOPE,first['cid'],proof(first,3))
    bank.observe(SCOPE,second['cid'],proof(second,0,'canceled'))
    assert bank.account(SCOPE)['blocked']=='capacity_deficit'
    broker=Broker();broker.positions={SYMBOL:3}
    broker.rows={first['cid']:proof(first,3),second['cid']:proof(second,0,'canceled')}
    original=broker.allocation_funds
    broker.allocation_funds=lambda:dict(original(),cash='60')
    managed=ManagedAccount(bank,SCOPE,'alice',broker)
    with pytest.raises(BankConflict):managed.repair_flat_account()
    sale=reserve(bank,trade=first['trade'],side='sell')
    broker.rows[sale['cid']]=proof(sale,3);bank.observe(SCOPE,sale['cid'],proof(sale,3))
    broker.positions={}
    result=managed.repair_flat_account()
    assert result['check_result']=='verified'
    assert bank.account(SCOPE)['available']=='60'
    assert bank.active(SCOPE)==[]
    assert broker.posts==0
