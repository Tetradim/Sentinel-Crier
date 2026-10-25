from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import pytest

from crier.policy_preview import SizingPolicy, preview_entry, preview_exit

FIXTURES=json.loads((Path(__file__).parent/'fixtures/policy-preview.json').read_text())


@pytest.mark.parametrize('kind,case',[(kind,case) for kind in ('entry','exit') for case in FIXTURES[kind]],ids=[case['id'] for kind in ('entry','exit') for case in FIXTURES[kind]])
def test_shared_scenarios(kind,case):
    actual=(preview_entry if kind=='entry' else preview_exit)(**case['input'])
    assert actual['preview_only'] is True
    assert {key:actual[key] for key in case['expected']}==case['expected']


@pytest.mark.parametrize('policy',[{'mode':'unknown'},{'mode':'fixed','fixed_quantity':True},{'mode':'ratio','ratio_bps':0},{'mode':'ratio','ratio_bps':10001},{'budget':'1'},{'mode':'budget','budget':'NaN'},{'max_entry_notional':1.1},{'max_entry_notional':'Infinity'},{'max_local_quantity':1001},{'max_source_quantity':False},{'unexpected':'value'}])
def test_strict_policy_rejects_ambiguous_or_unused_inputs(policy):
    with pytest.raises((TypeError,ValueError)): preview_entry(source_quantity=10,asset='stock',policy=policy)


@pytest.mark.parametrize('price',[0.2,'0','-1','NaN','Infinity','1e-2','0.123456789','999999999999999999999999999999'])
def test_decimal_prices_are_explicit_and_bounded(price):
    with pytest.raises(ValueError): preview_entry(source_quantity=10,asset='stock',limit_price=price)


def test_reference_does_not_mutate_legacy_settings_journal_or_submit(tmp_path):
    from test_intent_engine import Broker
    from crier.intent_engine import IntentEngine
    broker=Broker(); engine=IntentEngine(tmp_path/'intent.db',broker)
    saved=engine.save_settings({'enabled':True,'max_quantity':7,'mode':'bounded_limit'})
    before=(tmp_path/'intent.db').read_bytes()
    policy=SizingPolicy.from_legacy(saved)
    assert policy.mode=='source' and policy.max_source_quantity==policy.max_local_quantity==7
    assert preview_entry(source_quantity=8,asset='stock',policy=asdict(policy))['reason']=='source_quantity_cap'
    assert engine.load_settings()==saved and not broker.sent
    assert (tmp_path/'intent.db').read_bytes()==before


def test_budget_arithmetic_never_rounds_up_or_exceeds_the_explicit_budget():
    for cents in range(1,101):
        for budget in ('0.29','1.01','7.00'):
            price=Decimal(cents)/100
            result=preview_entry(source_quantity=1,asset='stock',limit_price=str(price),policy={'mode':'budget','budget':budget})
            if result['decision']=='eligible':
                quantity=result['target_quantity']
                assert quantity*price<=Decimal(budget)<(quantity+1)*price


def test_all_exit_modes_bound_quantity_by_tracked_and_available_units():
    for bought in range(1,8):
        for sold in range(bought+1):
            for available in (0,1,100):
                for mode in ('requested','proportional','close_tracked'):
                    result=preview_exit(mode=mode,requested_quantity=5,bought=bought,sold=sold,available=available,reconciled=True,source_entry_quantity=10,source_exit_cumulative=5)
                    assert 0<=result['quantity']<=min(bought-sold,available)


@pytest.mark.parametrize('field,value',[('bought',True),('sold',-1),('available',1.5),('reconciled','yes')])
def test_exit_input_types_cannot_be_coerced_into_authoritative_evidence(field,value):
    values=dict(requested_quantity=1,bought=1,sold=0,available=1,reconciled=True)
    values[field]=value
    with pytest.raises(ValueError): preview_exit(**values)


def test_preview_calculations_work_with_network_and_file_io_forbidden(monkeypatch):
    import builtins
    import socket
    def forbidden(*args,**kwargs): raise AssertionError('Preview must not perform I/O')
    monkeypatch.setattr(builtins,'open',forbidden)
    monkeypatch.setattr(socket,'socket',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(Path,'write_text',forbidden)
    monkeypatch.setattr(Path,'write_bytes',forbidden)
    for kind,function in (('entry',preview_entry),('exit',preview_exit)):
        for case in FIXTURES[kind]:
            assert function(**case['input'])['preview_only'] is True
