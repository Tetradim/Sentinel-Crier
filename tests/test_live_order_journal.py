"""Live-only order journal invariants. No broker API calls or trading fixtures."""

from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from crier.live_order_journal import (
    LiveJournalError, LiveOrderJournal, OrderIntent, order_set_digest,
)

T = "user-a"


def intent(group, broker, tenant=T, contracts=10, **overrides):
    values = dict(
        tenant_id=tenant, group_id=group, broker_id=broker, account_id="primary",
        contract_id="SPY-750-C-2026-10-16", client_order_id=str(uuid4()),
        action="buyToOpen", quantity=contracts, limit_price="0.60",
    )
    values.update(overrides)
    return OrderIntent(**values)


def confirm(journal, *orders, ttl=120):
    first = orders[0]
    journal.confirm_group(first.tenant_id, first.group_id,
                          expected_digest=order_set_digest(orders), ttl_seconds=ttl)


def fill(journal, order, execution_id, qty, price, at, broker_order_id="broker-order-1"):
    return journal.record_execution(
        order.tenant_id, order.client_order_id, execution_id, qty, price, at,
        broker_order_id, broker_id=order.broker_id, account_id=order.account_id)


def submitted(journal, order, accepted=True):
    journal.stage_group([order])
    confirm(journal, order)
    journal.reserve_submission(order.tenant_id, order.client_order_id)
    if accepted:
        journal.reconcile_order(order.tenant_id, order.client_order_id,
                                "accepted", "broker-order-1")


@pytest.fixture
def journal(tmp_path: Path):
    instance = LiveOrderJournal(tmp_path / "live-orders.sqlite3")
    yield instance
    instance.close()


def test_requires_explicit_confirmation_and_reserves_once(journal):
    group = str(uuid4())
    order = intent(group, "webull")
    journal.stage_group([order])
    with pytest.raises(LiveJournalError):
        journal.reserve_submission(order.tenant_id, order.client_order_id)
    confirm(journal, order)
    journal.reserve_submission(order.tenant_id, order.client_order_id)
    with pytest.raises(LiveJournalError):
        journal.reserve_submission(order.tenant_id, order.client_order_id)
    assert journal.orders_for_group(T, group)[0]["state"] == "submission_unknown"
    assert journal.verify_audit_chain()


def test_confirmation_is_bound_to_the_reviewed_orders(journal):
    group = str(uuid4())
    order = intent(group, "webull", contracts=1)
    journal.stage_group([order])
    shown = intent(group, "webull", contracts=1, client_order_id=order.client_order_id,
                   limit_price="0.10")
    with pytest.raises(LiveJournalError):
        journal.confirm_group(T, group, expected_digest=order_set_digest([shown]))
    with pytest.raises(LiveJournalError):
        journal.reserve_submission(T, order.client_order_id)
    assert journal.group_digest(T, group) == order_set_digest([order])


def test_confirmation_expires(tmp_path):
    now = [1_000.0]
    journal = LiveOrderJournal(tmp_path / "ttl.sqlite3", clock=lambda: now[0])
    try:
        order = intent(str(uuid4()), "webull")
        journal.stage_group([order])
        confirm(journal, order, ttl=60)
        now[0] += 61
        with pytest.raises(LiveJournalError):
            journal.reserve_submission(T, order.client_order_id)
        assert journal.orders_for_group(T, order.group_id)[0]["state"] == "unsubmitted"
    finally:
        journal.close()


def test_group_creation_is_atomic_and_rejects_duplicate_accounts(journal):
    group = str(uuid4())
    with pytest.raises(LiveJournalError):
        journal.stage_group([intent(group, "webull"), intent(group, "webull")])
    assert journal.orders_for_group(T, group) == []


def test_duplicate_group_and_cross_tenant_visibility(journal):
    group = str(uuid4())
    order = intent(group, "alpaca")
    journal.stage_group([order])
    with pytest.raises(Exception):
        journal.stage_group([order])
    assert journal.orders_for_group("another-user", group) == []
    with pytest.raises(LiveJournalError):
        journal.confirm_group("another-user", group,
                              expected_digest=order_set_digest([order]))


def test_partial_fills_then_complete_no_duplicates(journal):
    order = intent(str(uuid4()), "webull")
    submitted(journal, order)
    assert fill(journal, order, "exec-1", 6, "0.59", "2026-10-15T13:00:00+00:00")
    assert not fill(journal, order, "exec-1", 6, "0.59", "2026-10-15T13:00:00+00:00")
    assert journal.orders_for_group(T, order.group_id)[0]["state"] == "partially_filled"
    assert fill(journal, order, "exec-2", 4, "0.58", "2026-10-15T13:01:00+00:00")
    row = journal.orders_for_group(T, order.group_id)[0]
    assert (row["cumulative_filled"], row["state"]) == (10, "filled")
    assert row["needs_reconciliation"] == 0
    assert journal.verify_audit_chain()


def test_conflicting_duplicate_execution_fails_closed(journal):
    order = intent(str(uuid4()), "webull")
    submitted(journal, order, accepted=False)
    fill(journal, order, "execution-1", 2, "0.60", "2026-10-15T12:00:00+00:00", "broker-1")
    with pytest.raises(LiveJournalError):
        fill(journal, order, "execution-1", 3, "0.60", "2026-10-15T12:00:00+00:00", "broker-1")
    with pytest.raises(LiveJournalError):
        fill(journal, order, "execution-2", 9, "0.60", "2026-10-15T12:01:00+00:00", "broker-1")
    assert journal.orders_for_group(T, order.group_id)[0]["cumulative_filled"] == 2


def test_same_fill_with_different_timestamp_spelling_is_a_duplicate(journal):
    order = intent(str(uuid4()), "webull")
    submitted(journal, order)
    assert fill(journal, order, "e1", 2, "0.60", "2026-10-15T14:30:00Z")
    assert not fill(journal, order, "e1", 2, "0.60", "2026-10-15T14:30:00+00:00")
    assert not fill(journal, order, "e1", 2, "0.600", "2026-10-15T09:30:00-05:00")


def test_naive_execution_timestamp_is_rejected(journal):
    order = intent(str(uuid4()), "webull")
    submitted(journal, order)
    with pytest.raises(LiveJournalError):
        fill(journal, order, "e1", 2, "0.60", "2026-10-15T14:30:00")


def test_late_fill_after_cancel_is_recorded_and_flagged(journal):
    order = intent(str(uuid4()), "webull")
    submitted(journal, order)
    journal.reconcile_order(T, order.client_order_id, "canceled", "broker-order-1")
    assert fill(journal, order, "late-1", 2, "0.55", "2026-10-15T14:30:00Z")
    row = journal.orders_for_group(T, order.group_id)[0]
    assert (row["cumulative_filled"], row["state"], row["needs_reconciliation"]) == (2, "canceled", 1)
    assert [r["client_order_id"] for r in journal.orders_needing_reconciliation(T)] == [order.client_order_id]
    journal.clear_reconciliation(T, order.client_order_id, "matched broker statement")
    assert journal.orders_needing_reconciliation(T) == []
    with pytest.raises(LiveJournalError):
        journal.clear_reconciliation(T, order.client_order_id, "again")
    assert journal.verify_audit_chain()


def test_fill_outside_limit_is_recorded_and_flagged(journal):
    order = intent(str(uuid4()), "webull", limit_price="1.00")
    submitted(journal, order)
    assert fill(journal, order, "e1", 1, "9.99", "2026-10-15T14:30:00Z")
    assert journal.orders_for_group(T, order.group_id)[0]["needs_reconciliation"] == 1


def test_execution_must_belong_to_the_orders_broker_account(journal):
    order = intent(str(uuid4()), "webull")
    submitted(journal, order)
    for broker, account in (("alpaca", "primary"), ("webull", "someone-else")):
        with pytest.raises(LiveJournalError):
            journal.record_execution(T, order.client_order_id, "e1", 1, "0.60",
                                     "2026-10-15T14:30:00Z", "broker-order-1",
                                     broker_id=broker, account_id=account)


def test_reused_execution_id_on_a_different_broker_order_is_not_a_conflict(journal):
    first, second = intent(str(uuid4()), "webull"), intent(str(uuid4()), "webull")
    submitted(journal, first, accepted=False)
    journal.stage_group([second])
    confirm(journal, second)
    journal.reserve_submission(T, second.client_order_id)
    assert fill(journal, first, "1", 1, "0.60", "2026-10-15T14:30:00Z", "B-1")
    assert fill(journal, second, "1", 1, "0.60", "2026-10-15T14:30:00Z", "B-2")


def test_timeout_never_infers_rejection(journal):
    order = intent(str(uuid4()), "alpaca")
    submitted(journal, order, accepted=False)
    assert journal.orders_for_group(T, order.group_id)[0]["state"] == "submission_unknown"
    with pytest.raises(LiveJournalError):
        journal.reconcile_order(T, order.client_order_id, "filled", "order-1")


def test_cannot_reconcile_unsubmitted_order(journal):
    order = intent(str(uuid4()), "alpaca")
    journal.stage_group([order])
    with pytest.raises(LiveJournalError):
        journal.reconcile_order(T, order.client_order_id, "accepted", "order-1")


@pytest.mark.parametrize("price", ["NaN", "-1", "Infinity", "0", "0.00", " 1.25 ", "1e30",
                                   "1,5", "100000.01", "1.23456", ""])
def test_invalid_price_fails_closed(journal, price):
    with pytest.raises(LiveJournalError):
        journal.stage_group([intent(str(uuid4()), "webull", limit_price=price)])


@pytest.mark.parametrize("contracts", [0, -1, 1001, True, 1.5])
def test_invalid_quantity_fails_closed(journal, contracts):
    with pytest.raises(LiveJournalError):
        journal.stage_group([intent(str(uuid4()), "webull", contracts=contracts)])


def test_noncanonical_uuid_spellings_are_rejected(journal):
    canonical = str(uuid4())
    for spelling in (canonical.upper(), canonical.replace("-", ""), "{" + canonical + "}",
                     "urn:uuid:" + canonical):
        with pytest.raises(LiveJournalError):
            journal.stage_group([intent(str(uuid4()), "webull", client_order_id=spelling)])
        with pytest.raises(LiveJournalError):
            journal.stage_group([intent(spelling, "webull")])


def test_audit_tampering_is_detected(journal):
    journal.stage_group([intent(str(uuid4()), "webull")])
    assert journal.verify_audit_chain()
    journal._db.execute("UPDATE audit SET details='tampered' WHERE seq=1")
    assert not journal.verify_audit_chain()


def test_reopen_preserves_unknown_reservation(tmp_path):
    path = tmp_path / "durable.sqlite3"
    order = intent(str(uuid4()), "webull")
    first = LiveOrderJournal(path)
    first.stage_group([order])
    confirm(first, order)
    first.reserve_submission(T, order.client_order_id)
    first.close()
    reopened = LiveOrderJournal(path)
    try:
        assert reopened.orders_for_group(T, order.group_id)[0]["state"] == "submission_unknown"
        with pytest.raises(LiveJournalError):
            reopened.reserve_submission(T, order.client_order_id)
    finally:
        reopened.close()


def test_old_schema_database_is_refused_not_silently_reused(tmp_path):
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE orders (tenant_id TEXT)")
    db.commit()
    db.close()
    with pytest.raises(LiveJournalError):
        LiveOrderJournal(path)


def test_reserve_group_is_all_or_nothing(tmp_path):
    now = [1_000.0]
    journal = LiveOrderJournal(tmp_path / "group.sqlite3", clock=lambda: now[0])
    try:
        group = str(uuid4())
        orders = [intent(group, "webull"), intent(group, "alpaca")]
        journal.stage_group(orders)
        with pytest.raises(LiveJournalError):            # not confirmed yet
            journal.reserve_group(T, group)
        confirm(journal, *orders, ttl=60)
        now[0] += 61
        with pytest.raises(LiveJournalError):            # confirmation lapsed
            journal.reserve_group(T, group)
        assert {r["state"] for r in journal.orders_for_group(T, group)} == {"unsubmitted"}
    finally:
        journal.close()


def test_reserve_group_reserves_every_order_once(journal):
    group = str(uuid4())
    orders = [intent(group, "webull"), intent(group, "alpaca")]
    journal.stage_group(orders)
    confirm(journal, *orders)
    ids = journal.reserve_group(T, group)
    assert sorted(ids) == sorted(o.client_order_id for o in orders)
    assert {r["state"] for r in journal.orders_for_group(T, group)} == {"submission_unknown"}
    with pytest.raises(LiveJournalError):
        journal.reserve_group(T, group)
    with pytest.raises(LiveJournalError):                # a leg cannot be reserved again either
        journal.reserve_submission(T, orders[0].client_order_id)
    assert journal.verify_audit_chain()
