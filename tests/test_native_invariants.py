"""Shared semantic examples drive the real durable bank and continuity clock."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from crier.allocation_bank import AccountBank, BankConflict
from crier.entry_clock import ClockUncertain, EntryClock
from crier.host_allocation import Scope

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/native-invariants.json').read_text())
assert FIXTURE['version'] == 1, 'Unsupported native-invariants fixture version'


@pytest.mark.parametrize('case', FIXTURE['clock'], ids=lambda case: case['id'])
def test_shared_clock(case):
    values = [case['anchor_wall_ms'] / 1000, case['anchor_mono_ms'] / 1000]
    clock = EntryClock(lambda: values[0], lambda: values[1])
    for sample in case['samples']:
        values[:] = [sample['wall_ms'] / 1000, sample['mono_ms'] / 1000]
        if sample.get('uncertain'):
            with pytest.raises(ClockUncertain):
                clock.read()
        else:
            reading = clock.read()
            assert reading.effective == pytest.approx(sample['effective_ms'] / 1000)
            assert reading.wall == values[0]


@pytest.mark.parametrize('case', FIXTURE['bank'], ids=lambda case: case['id'])
def test_shared_bank(case, tmp_path):
    path = tmp_path / 'bank.sqlite3'
    bank = AccountBank(path)
    scopes = {name: Scope('alpaca', name, 'paper') for name in ('one', 'two')}
    for scope in scopes.values():
        bank.enable(scope, '100', '100')
        bank.inventory(scope, {})  # Python establishes its external baseline separately.
        for route in ('alice', 'bob'):
            bank.configure(scope, route, 'stock', {'mode': 'dollars', 'value': '100'})
    reservations = {}
    for step in case['steps']:
        if step['op'] == 'restart':
            bank = AccountBank(path)
            continue
        account = step.get('account', 'one')
        scope = scopes[account]

        def perform():
            if step['op'] == 'reserve':
                side = 'sell' if step['sell'] else 'buy'
                cid = bank.client_id(scope, step['route'], step['trade'], step['event'], side, 0)
                bank.reserve(scope, step['route'], step['trade'], step['event'], cid,
                             'SPY', 'stock', 1, side, step['quantity'], '10', '0',
                             cash='100', equity='100', ordinal=0)
                reservations[step['alias']] = (cid, step)
            elif step['op'] == 'observe':
                cid, original = reservations[step['alias']]
                bank.observe(scope, cid, dict(id='broker-' + cid, client_order_id=cid,
                    symbol='SPY', side='sell' if original['sell'] else 'buy',
                    qty=str(original['quantity']), filled_qty=str(step['filled']),
                    filled_avg_price='10', status=step['status']))
            elif step['op'] == 'inventory':
                bank.inventory(scope, step['positions'])
            else:
                assert step['op'] == 'check'

        if step.get('refused'):
            with pytest.raises(BankConflict):
                perform()
        else:
            perform()
        actual = bank.account(scope)
        assert Decimal(actual['available']) == Decimal(step['available']), step
        assert len(bank.active(scope)) == step['active'], step
        orders = bank.orders(scope, active_only=False)
        assert len(orders) == step['orders'], step
        assert bool(actual['blocked']) == step.get('blocked', False), step
        if step['op'] == 'observe':
            cid, original = reservations[step['alias']]
            order = next(order for order in orders if order['cid'] == cid)
            assert (order['filled'], order['status']) == (step.get('expected_filled', step['filled']), step['status'])
            owner = bank.history(scope, order['bank_id'])
            assert (owner['route'], owner['trade']) == (original['route'], original['trade'])
