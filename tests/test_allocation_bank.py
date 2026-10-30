import concurrent.futures
from pathlib import Path
from uuid import uuid4
import pytest
from crier.allocation_bank import AccountBank, BankConflict
from crier.host_allocation import Scope

SCOPE=Scope("alpaca","account-one","paper")
SYMBOL="SPY261218C00750000"

def setup_bank(tmp_path,cash="1000"):
    bank=AccountBank(tmp_path/"bank.sqlite3")
    bank.enable(SCOPE,cash,"10000")
    for route in ("alice","dave"):
        bank.configure(SCOPE,route,"option",{"mode":"dollars","value":"500"})
    return bank


def test_flat_inventory_cannot_silently_adopt_late_or_external_fills(tmp_path):
    bank=setup_bank(tmp_path)
    bank.inventory(SCOPE,{})
    with pytest.raises(BankConflict):bank.inventory(SCOPE,{SYMBOL:1})
    assert bank.account(SCOPE)['blocked']=='position_discrepancy'


def test_inventory_recovery_does_not_clear_unrelated_evidence_block(tmp_path):
    bank=setup_bank(tmp_path);bank.inventory(SCOPE,{})
    with pytest.raises(BankConflict):bank.inventory(SCOPE,{SYMBOL:1})
    bank.inventory(SCOPE,{})
    assert bank.account(SCOPE)['blocked']==''
    bank.block(SCOPE,'late_terminal_fill')
    with pytest.raises(BankConflict):bank.inventory(SCOPE,{SYMBOL:1})
    bank.inventory(SCOPE,{})
    assert bank.account(SCOPE)['blocked']=='late_terminal_fill'


def test_repeated_identical_broker_proof_does_not_grow_audit_or_charge_twice(tmp_path):
    bank=setup_bank(tmp_path);order=reserve(bank)
    bank.observe(SCOPE,order['cid'],proof(order,3))
    with bank.db() as db:before=db.execute('SELECT COUNT(*) FROM bank_audit').fetchone()[0]
    bank.observe(SCOPE,order['cid'],proof(order,3))
    with bank.db() as db:after=db.execute('SELECT COUNT(*) FROM bank_audit').fetchone()[0]
    assert after==before
    assert bank.account(SCOPE)['available']=='940'


def reserve(bank,route="alice",trade=None,event=None,side="buy",qty=3,price="0.20",cid=None):
    trade=trade or str(uuid4());event=event or str(uuid4())
    cid=cid or bank.client_id(SCOPE,route,trade,event,side,0)
    return bank.reserve(SCOPE,route,trade,event,cid,SYMBOL,"option",100,side,qty,price,"0",cash="1000",equity="10000",ordinal=0)


def proof(order,filled,status="filled",price="0.20"):
    return dict(id="broker-"+order["cid"],client_order_id=order["cid"],symbol=SYMBOL,side=order["side"],qty=str(order["quantity"]),filled_qty=str(filled),filled_avg_price=price if filled else None,status=status)


def test_ids_and_client_order_ids_are_scoped_to_host_and_account(tmp_path):
    bank=setup_bank(tmp_path)
    event=str(uuid4());trade=str(uuid4())
    a=reserve(bank,trade=trade,event=event)
    assert bank.client_id(SCOPE,"alice",trade,event,"buy",0)==a["cid"]
    assert bank.client_id(SCOPE,"dave",trade,event,"buy",0)!=a["cid"]
    other=Scope("alpaca","account-two","paper")
    assert bank.client_id(other,"alice",trade,event,"buy",0)!=a["cid"]
    with pytest.raises(BankConflict):reserve(bank,"dave",trade,event)
    assert len(bank.active(SCOPE))==1


def test_two_hosts_own_separate_lots_for_identical_contracts(tmp_path):
    bank=setup_bank(tmp_path)
    alice=reserve(bank,qty=3);dave=reserve(bank,"dave",qty=5)
    bank.observe(SCOPE,alice["cid"],proof(alice,3))
    bank.observe(SCOPE,dave["cid"],proof(dave,5))
    exit_a=reserve(bank,trade=alice["trade"],side="sell",qty=3,price="0.22")
    bank.observe(SCOPE,exit_a["cid"],proof(exit_a,3,price="0.22"))
    assert [row["units"] for row in bank.active(SCOPE)]==[5]
    assert bank.history(SCOPE,alice["bank_id"])["state"]=="closed"
    assert bank.history(SCOPE,dave["bank_id"])["units"]==5


def test_partial_cancel_keeps_filled_holdings_and_releases_only_unfilled_cash(tmp_path):
    bank=setup_bank(tmp_path)
    buy=reserve(bank,qty=5)
    bank.observe(SCOPE,buy["cid"],proof(buy,2,"partially_filled"))
    bank.invalidate(SCOPE,"alice",buy["trade"],"canceled")
    assert bank.account(SCOPE)["available"]=="900"
    bank.observe(SCOPE,buy["cid"],proof(buy,2,"canceled"))
    assert bank.account(SCOPE)["available"]=="960"
    assert bank.active(SCOPE)[0]["units"]==2
    sell=reserve(bank,trade=buy["trade"],side="sell",qty=2)
    bank.observe(SCOPE,sell["cid"],proof(sell,2))
    assert bank.active(SCOPE)==[]


def test_unknown_submission_survives_restart_and_replay_cannot_reserve_twice(tmp_path):
    bank=setup_bank(tmp_path)
    buy=reserve(bank,qty=5)
    restarted=AccountBank(bank.path)
    again=reserve(restarted,trade=buy["trade"],event=buy["event"],qty=5,cid=buy["cid"])
    assert again["existing"] and restarted.account(SCOPE)["available"]=="900"
    assert restarted.active(SCOPE)[0]["pending_buy_units"]==5
    with pytest.raises(BankConflict):restarted.retire(SCOPE,"alice",buy["trade"],"invalid")


def test_confirmed_empty_id_leaves_active_bank_but_never_reuses_identity(tmp_path):
    bank=setup_bank(tmp_path)
    buy=reserve(bank)
    bank.invalidate(SCOPE,"alice",buy["trade"],"canceled")
    bank.observe(SCOPE,buy["cid"],proof(buy,0,"canceled"))
    assert bank.active(SCOPE)==[]
    with pytest.raises(BankConflict):reserve(bank,trade=buy["trade"])
    new=reserve(bank)
    assert new["bank_id"]>buy["bank_id"]
    assert bank.history(SCOPE,buy["bank_id"])["state"]=="closed"


def test_simultaneous_hosts_cannot_overallocate_one_account(tmp_path):
    bank=setup_bank(tmp_path,cash="100")
    def attempt(route):
        try:return reserve(bank,route,qty=3)
        except BankConflict:return None
    with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(attempt,["alice","dave"]))
    assert sum(item is not None for item in results)==1
    assert bank.account(SCOPE)["available"]=="40"


def test_pending_exits_cannot_sell_another_hosts_contracts(tmp_path):
    bank=setup_bank(tmp_path)
    buy=reserve(bank,qty=3);bank.observe(SCOPE,buy["cid"],proof(buy,3))
    reserve(bank,trade=buy["trade"],side="sell",qty=2)
    with pytest.raises(BankConflict):reserve(bank,trade=buy["trade"],side="sell",qty=2)
    with pytest.raises(BankConflict):reserve(bank,"dave",trade=buy["trade"],side="sell",qty=1)


@pytest.mark.parametrize("changes",[{"filled_qty":"4"},{"filled_qty":"1.5"},{"symbol":"AAPL"},{"side":"sell"},{"client_order_id":"wrong"},{"qty":"2"},{"filled_avg_price":"NaN"},{"filled_avg_price":"0.21"}])
def test_contradictory_broker_evidence_blocks_account_without_releasing_budget(tmp_path,changes):
    bank=setup_bank(tmp_path);buy=reserve(bank)
    snapshot=proof(buy,3);snapshot.update(changes)
    with pytest.raises(BankConflict):bank.observe(SCOPE,buy["cid"],snapshot)
    assert bank.account(SCOPE)["blocked"] and bank.account(SCOPE)["available"]=="940"
    with pytest.raises(BankConflict):reserve(bank,"dave")


def test_cumulative_fill_decrease_and_terminal_reopening_are_not_silently_applied(tmp_path):
    bank=setup_bank(tmp_path);buy=reserve(bank)
    bank.observe(SCOPE,buy["cid"],proof(buy,2,"partially_filled"))
    with pytest.raises(BankConflict):bank.observe(SCOPE,buy["cid"],proof(buy,1,"partially_filled"))
    assert bank.active(SCOPE)[0]["units"]==2


def test_funds_and_positions_reconcile_without_assigning_external_holdings(tmp_path):
    bank=setup_bank(tmp_path)
    bank.inventory(SCOPE,{SYMBOL:100})
    buy=reserve(bank,qty=3);bank.observe(SCOPE,buy["cid"],proof(buy,3))
    bank.inventory(SCOPE,{SYMBOL:103})
    with pytest.raises(BankConflict):bank.inventory(SCOPE,{SYMBOL:102})
    assert bank.active(SCOPE)[0]["units"]==3 and bank.account(SCOPE)["blocked"]


def test_confirmed_loss_reduces_reusable_money_and_profit_is_not_auto_compounded(tmp_path):
    bank=setup_bank(tmp_path)
    buy=reserve(bank,qty=5);bank.observe(SCOPE,buy["cid"],proof(buy,5))
    sell=reserve(bank,trade=buy["trade"],side="sell",qty=5,price="0.18")
    bank.observe(SCOPE,sell["cid"],proof(sell,5,price="0.18"))
    assert bank.account(SCOPE)["available"]=="990"


def test_pool_allocation_percent_and_unit_caps_share_account_capacity(tmp_path):
    bank=setup_bank(tmp_path)
    bank.configure(SCOPE,"alice","option",{"mode":"units","value":"2"})
    with pytest.raises(BankConflict):reserve(bank,qty=3)
    bank.configure(SCOPE,"alice","option",{"mode":"equity_percent","value":"0.5"})
    with pytest.raises(BankConflict):reserve(bank,qty=3)
    buy=reserve(bank,qty=2)
    assert buy["quantity"]==2


def test_exit_fee_can_be_paid_from_sale_without_borrowing_another_host_cash(tmp_path):
    bank=setup_bank(tmp_path,cash="60")
    buy=reserve(bank,qty=3);bank.observe(SCOPE,buy["cid"],proof(buy,3))
    event=str(uuid4());cid=bank.client_id(SCOPE,"alice",buy["trade"],event,"sell",0)
    sell=bank.reserve(SCOPE,"alice",buy["trade"],event,cid,SYMBOL,"option",100,"sell",3,"0.20","1",cash="0",equity="10000",ordinal=0)
    bank.observe(SCOPE,cid,proof(sell,1,"partially_filled"))
    assert bank.account(SCOPE)["available"]=="19"
    bank.observe(SCOPE,cid,proof(sell,3))
    assert bank.account(SCOPE)["available"]=="59"


def test_buy_fee_is_counted_once_in_host_pool(tmp_path):
    bank=setup_bank(tmp_path)
    bank.configure(SCOPE,"alice","option",{"mode":"dollars","value":"41"})
    event=str(uuid4());trade=str(uuid4());cid=bank.client_id(SCOPE,"alice",trade,event,"buy",0)
    buy=bank.reserve(SCOPE,"alice",trade,event,cid,SYMBOL,"option",100,"buy",1,"0.20","1",cash="1000",equity="10000",ordinal=0)
    bank.observe(SCOPE,cid,proof(buy,1))
    second=reserve(bank,qty=1)
    assert second["quantity"]==1


def test_late_terminal_fill_restores_original_id_and_blocks_new_entries(tmp_path):
    bank=setup_bank(tmp_path,cash="60")
    buy=reserve(bank,qty=3);bank.invalidate(SCOPE,"alice",buy["trade"],"canceled")
    bank.observe(SCOPE,buy["cid"],proof(buy,0,"canceled"))
    other=reserve(bank,"dave",qty=3)
    bank.observe(SCOPE,buy["cid"],proof(buy,3))
    assert bank.active(SCOPE)[0]["id"]==buy["bank_id"]
    assert bank.active(SCOPE)[0]["units"]==3
    assert bank.account(SCOPE)["blocked"] and bank.account(SCOPE)["available"]=="0"
