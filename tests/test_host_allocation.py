from datetime import datetime, timedelta, timezone
import pytest
from crier.host_allocation import Scope, Funds, Usage, Allocation, preview

NOW=datetime(2026,10,29,15,tzinfo=timezone.utc)
SCOPE=Scope("alpaca","account-a","paper")

def check(pool=Allocation("dollars","2000"),size=Allocation("units","3"),**changes):
    args=dict(scope=SCOPE,host_id="host-a",funds=Funds(SCOPE,"10000","1000",NOW,"snapshot-1","USD"),
              usage=Usage(SCOPE,"host-a",0,"0","option"),pool=pool,sizing=size,asset="option",multiplier=100,
              buy_limit="0.20",fee_reserve="0",max_units=1000,now=NOW)
    if changes.get("asset")=="stock" and "usage" not in changes:args["usage"]=Usage(SCOPE,"host-a",0,"0","stock")
    args.update(changes)
    return preview(**args)


def test_fixed_contracts_and_option_multiplier():
    result=check()
    assert result["preview_only"] and result["decision"]=="eligible"
    assert result["target_units"]==3 and result["reserved_notional"]=="60"


def test_dollar_entry_is_separate_from_reusable_host_pool():
    result=check(size=Allocation("dollars","300"))
    assert result["target_units"]==15 and result["remaining_pool"]=="2000"


def test_percentage_uses_destination_equity_not_available_cash():
    result=check(pool=Allocation("equity_percent","20"),size=Allocation("equity_percent","2"))
    assert result["target_units"]==10 and result["remaining_pool"]=="2000"


def test_pending_and_held_exposure_reduce_pool_without_releasing_on_cancel_request():
    result=check(pool=Allocation("dollars","100"),usage=Usage(SCOPE,"host-a",2,"80","option"))
    assert result["decision"]=="skip" and result["reason"]=="allocation_capacity"
    assert result["target_units"]==0


def test_explicit_downsize_can_fit_remaining_capacity():
    result=check(pool=Allocation("dollars","100"),usage=Usage(SCOPE,"host-a",2,"80","option"),allow_downsize=True)
    assert result["target_units"]==1


def test_contract_pool_caps_total_units_not_each_independent_trade():
    result=check(pool=Allocation("units","5"),usage=Usage(SCOPE,"host-a",4,"80","option"))
    assert result["decision"]=="skip"
    assert check(pool=Allocation("units","5"),usage=Usage(SCOPE,"host-a",4,"80","option"),allow_downsize=True)["target_units"]==1


def test_equity_drop_or_zero_allocation_does_not_generate_exit():
    result=check(pool=Allocation("equity_percent","1"),usage=Usage(SCOPE,"host-a",8,"160","option"))
    assert result["decision"]=="skip" and result["target_units"]==0
    assert check(pool=Allocation("dollars","0"))["decision"]=="skip"
    assert "action" not in result


@pytest.mark.parametrize("changes",[
 {"funds":Funds(Scope("alpaca","other","paper"),"10000","1000",NOW,"s","USD")},
 {"funds":Funds(Scope("alpaca","account-a","live"),"10000","1000",NOW,"s","USD")},
 {"funds":Funds(Scope("webull","account-a","paper"),"10000","1000",NOW,"s","USD")},
 {"usage":Usage(SCOPE,"other-host",0,"0","option")},
 {"usage":Usage(Scope("alpaca","other","paper"),"host-a",0,"0","option")},
])
def test_scope_and_host_provenance_cannot_cross(changes):
    assert check(**changes)["decision"]=="blocked"


@pytest.mark.parametrize("at",[NOW-timedelta(seconds=11),NOW+timedelta(seconds=1)])
def test_stale_or_future_account_snapshot_blocks(at):
    assert check(funds=Funds(SCOPE,"10000","1000",at,"s","USD"))["reason"]=="account_snapshot_unavailable"


def test_cash_capacity_and_explicit_fees_are_respected():
    assert check(funds=Funds(SCOPE,"10000","60",NOW,"s","USD"),fee_reserve="1")["decision"]=="skip"
    result=check(funds=Funds(SCOPE,"10000","60",NOW,"s","USD"),fee_reserve="1",allow_downsize=True)
    assert result["target_units"]==2 and result["reserved_notional"]=="41"


def test_no_force_minimum_unit_or_fractional_contract():
    assert check(size=Allocation("dollars","19.99"))["reason"]=="below_one_unit"
    assert check(size=Allocation("dollars","59.99"))["target_units"]==2


def test_stocks_use_share_units_and_one_multiplier():
    assert check(asset="stock",multiplier=1,buy_limit="10")["reserved_notional"]=="30"
    assert check(multiplier=10)["reason"]=="unsupported_instrument"


def test_market_orders_cannot_claim_a_strict_monetary_reservation():
    assert check(buy_limit=None)["reason"]=="bounded_price_required"


@pytest.mark.parametrize("value",["NaN","Infinity","-1",1.5,True,"1e3"])
def test_invalid_numeric_inputs_fail_closed(value):
    with pytest.raises(ValueError): check(size=Allocation("dollars",value))


def test_percentage_over_100_and_noninteger_units_rejected():
    with pytest.raises(ValueError): check(pool=Allocation("equity_percent","100.01"))
    with pytest.raises(ValueError): check(size=Allocation("units","1.5"))


def test_malformed_funds_and_timestamps_rejected():
    with pytest.raises(ValueError): check(funds=Funds(SCOPE,"10000","1000",NOW.replace(tzinfo=None),"s","USD"))
    with pytest.raises(ValueError): check(max_units=True)
    with pytest.raises(ValueError): check(funds=Funds(SCOPE,"10000","1000",NOW,"","USD"))


def test_currency_and_asset_pool_units_are_not_interchangeable():
    assert check(funds=Funds(SCOPE,"10000","1000",NOW,"s","JPY"))["reason"]=="unsupported_currency"
    assert check(usage=Usage(SCOPE,"host-a",0,"0","stock"))["reason"]=="asset_pool_mismatch"


def test_fractional_cent_equity_allocation_rounds_down():
    result=check(pool=Allocation("equity_percent","0.333"),size=Allocation("equity_percent","0.333"),
                 funds=Funds(SCOPE,"10001","1000",NOW,"s","USD"),buy_limit="0.01")
    assert result["remaining_pool"]=="33.3" and result["target_units"]==33


def test_portable_allocation_cases_for_native_parity():
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/"fixtures/host-allocation.json").read_text(encoding="utf8"))
    assert fixture["version"]==1 and len(fixture["cases"])==5
    c=fixture["common"]; scope=Scope(c["broker"],c["account"],c["environment"])
    now=datetime.fromisoformat(c["observed_at"])
    funds=Funds(scope,c["equity"],c["spendable_cash"],now,c["snapshot_revision"],c["currency"])
    for case in fixture["cases"]:
        usage=Usage(scope,c["host_id"],case.get("usage_units",0),case.get("usage_notional","0"),c["asset"])
        result=preview(scope=scope,host_id=c["host_id"],funds=funds,usage=usage,
                       pool=Allocation(**case["pool"]),sizing=Allocation(**case["sizing"]),
                       asset=c["asset"],multiplier=c["multiplier"],buy_limit=c["buy_limit"],
                       fee_reserve=c["fee_reserve"],max_units=c["max_units"],now=now,
                       allow_downsize=case.get("allow_downsize",False))
        assert result["preview_only"]
        for name,value in case["expected"].items():assert result[name]==value,case["name"]
