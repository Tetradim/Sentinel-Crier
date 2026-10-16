"""Live-only order journal invariants. No broker API calls or trading fixtures."""

from pathlib import Path
from uuid import uuid4

import pytest

from crier.live_order_journal import (
    LiveJournalError, LiveOrderJournal, OrderIntent,
)


def intent(group, broker, tenant="user-a", contracts=10):
    return OrderIntent(
        tenant_id=tenant, group_id=group, broker_id=broker, account_id="primary",
        contract_id="SPY-750-C-2026-10-16", client_order_id=str(uuid4()),
        action="buyToOpen", quantity=contracts, limit_price="0.60",
    )


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
    journal.confirm_group(order.tenant_id, group)
    journal.reserve_submission(order.tenant_id, order.client_order_id)
    with pytest.raises(LiveJournalError):
        journal.reserve_submission(order.tenant_id, order.client_order_id)
    assert journal.orders_for_group("user-a", group)[0]["state"] == "submission_unknown"
    assert journal.verify_audit_chain()


def test_group_creation_is_atomic_and_rejects_duplicate_accounts(journal):
    group = str(uuid4())
    with pytest.raises(LiveJournalError):
        journal.stage_group([intent(group, "webull"), intent(group, "webull")])
    assert journal.orders_for_group("user-a", group) == []


def test_duplicate_group_and_cross_tenant_visibility(journal):
    group = str(uuid4())
    order = intent(group, "alpaca")
    journal.stage_group([order])
    with pytest.raises(Exception):
        journal.stage_group([order])
    assert journal.orders_for_group("another-user", group) == []
    with pytest.raises(LiveJournalError):
        journal.confirm_group("another-user", group)


def test_partial_fills_then_complete_no_duplicates(journal):
    group = str(uuid4())
    order = intent(group, "webull")
    journal.stage_group([order])
    journal.confirm_group("user-a", group)
    journal.reserve_submission("user-a", order.client_order_id)
    journal.reconcile_order("user-a", order.client_order_id, "accepted", "broker-order-1")
    assert journal.record_execution("user-a", order.client_order_id, "exec-1", 6, "0.61",
                                    "2026-10-15T13:00:00+00:00", "broker-order-1")
    assert not journal.record_execution("user-a", order.client_order_id, "exec-1", 6, "0.61",
                                        "2026-10-15T13:00:00+00:00", "broker-order-1")
    assert journal.orders_for_group("user-a", group)[0]["state"] == "partially_filled"
    assert journal.record_execution("user-a", order.client_order_id, "exec-2", 4, "0.62",
                                    "2026-10-15T13:01:00+00:00", "broker-order-1")
    row = journal.orders_for_group("user-a", group)[0]
    assert (row["cumulative_filled"], row["state"]) == (10, "filled")
    assert journal.verify_audit_chain()


def test_conflicting_duplicate_execution_fails_closed(journal):
    group = str(uuid4())
    order = intent(group, "webull")
    journal.stage_group([order])
    journal.confirm_group("user-a", group)
    journal.reserve_submission("user-a", order.client_order_id)
    args = ("user-a", order.client_order_id, "execution-1", 2,
            "0.60", "2026-10-15T12:00:00+00:00", "broker-1")
    journal.record_execution(*args)
    with pytest.raises(LiveJournalError):
        journal.record_execution("user-a", order.client_order_id, "execution-1", 3,
                                 "0.60", "2026-10-15T12:00:00+00:00", "broker-1")
    with pytest.raises(LiveJournalError):
        journal.record_execution("user-a", order.client_order_id, "execution-2", 9,
                                 "0.60", "2026-10-15T12:01:00+00:00", "broker-1")
    assert journal.orders_for_group("user-a", group)[0]["cumulative_filled"] == 2


def test_timeout_never_infers_rejection(journal):
    group = str(uuid4())
    order = intent(group, "alpaca")
    journal.stage_group([order])
    journal.confirm_group("user-a", group)
    journal.reserve_submission("user-a", order.client_order_id)
    assert journal.orders_for_group("user-a", group)[0]["state"] == "submission_unknown"
    with pytest.raises(LiveJournalError):
        journal.reconcile_order("user-a", order.client_order_id, "filled", "order-1")


def test_cannot_reconcile_unsubmitted_order(journal):
    group = str(uuid4())
    order = intent(group, "alpaca")
    journal.stage_group([order])
    with pytest.raises(LiveJournalError):
        journal.reconcile_order("user-a", order.client_order_id, "accepted", "order-1")


def test_invalid_price_and_order_identifiers_fail_closed(journal):
    group = str(uuid4())
    bad = intent(group, "webull")
    for price in ("NaN", "-1", "Infinity", "0"):
        with pytest.raises(LiveJournalError):
            journal.stage_group([OrderIntent(
                **{**bad.__dict__, "limit_price": price}
            )])
    assert journal.orders_for_group("user-a", group) == []


def test_audit_tampering_is_detected(journal):
    group = str(uuid4())
    journal.stage_group([intent(group, "webull")])
    assert journal.verify_audit_chain()
    journal._db.execute("UPDATE audit SET details='tampered' WHERE seq=1")
    assert not journal.verify_audit_chain()


def test_reopen_preserves_unknown_reservation(tmp_path):
    path = tmp_path / "durable.sqlite3"
    group = str(uuid4())
    order = intent(group, "webull")
    first = LiveOrderJournal(path)
    first.stage_group([order])
    first.confirm_group("user-a", group)
    first.reserve_submission("user-a", order.client_order_id)
    first.close()
    reopened = LiveOrderJournal(path)
    try:
        assert reopened.orders_for_group("user-a", group)[0]["state"] == "submission_unknown"
        with pytest.raises(LiveJournalError):
            reopened.reserve_submission("user-a", order.client_order_id)
    finally:
        reopened.close()
