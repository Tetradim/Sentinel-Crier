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
    bank=setup_bank(tmp_path);broker=Broker()
    managed=ManagedAccount(bank,SCOPE,'alice',broker)
    report=managed.recovery_check()
    assert report['broker_checked'] is True
    assert broker.posts==0
    assert report['can_clear'] is False


def test_unknown_check_retains_cash_and_reports_unresolved(tmp_path):
    from crier.managed_account import ManagedAccount
    from test_managed_account import Broker
    bank=setup_bank(tmp_path);reserve(bank);before=bank.account(SCOPE)
    broker=Broker();report=ManagedAccount(bank,SCOPE,'alice',broker).recovery_check()
    assert report['check_result']=='unresolved'
    assert bank.account(SCOPE)==before
    assert broker.posts==0
