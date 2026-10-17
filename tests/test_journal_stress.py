"""Bounded local concurrency/precision checks; never contacts a broker."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

from crier.live_order_journal import LiveOrderJournal, OrderIntent, LiveJournalError


def test_concurrent_fills_deduplicate_and_survive_restart(tmp_path):
    path = tmp_path / "stress.sqlite3"
    journal = LiveOrderJournal(path)
    orders = []
    try:
        for i in range(100):
            order = OrderIntent("paper-test", str(uuid4()), "alpaca", "paper",
                                "TEST-CONTRACT", str(uuid4()), "buyToOpen", 10, "1.23")
            journal.stage_group([order])
            journal.confirm_group(order.tenant_id, order.group_id)
            journal.reserve_submission(order.tenant_id, order.client_order_id)
            orders.append(order)

        def ingest(item):
            order, index = item
            return journal.record_execution(
                order.tenant_id, order.client_order_id,
                order.client_order_id + "-" + str(index), 1, "1.23",
                "2026-10-16T15:00:00+00:00", order.client_order_id)

        unique = [(order, i) for order in orders for i in range(10)]
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(ingest, unique * 3))
        assert sum(results) == 1000
        assert journal.verify_audit_chain()
    finally:
        journal.close()
    journal = LiveOrderJournal(path)
    try:
        for order in orders:
            row, = journal.orders_for_group(order.tenant_id, order.group_id)
            assert row["state"] == "filled"
            assert row["cumulative_filled"] == row["quantity"] == 10
            assert Decimal(row["limit_price"]) == Decimal("1.23")
        assert journal.verify_audit_chain()
    finally:
        journal.close()


def test_concurrent_submission_reservation_has_exactly_one_winner(tmp_path):
    journal = LiveOrderJournal(tmp_path / "reservation.sqlite3")
    order = OrderIntent("paper-test", str(uuid4()), "alpaca", "paper",
                        "TEST-CONTRACT", str(uuid4()), "buyToOpen", 1, "0.01")
    try:
        journal.stage_group([order])
        journal.confirm_group(order.tenant_id, order.group_id)

        def reserve(_):
            try:
                journal.reserve_submission(order.tenant_id, order.client_order_id)
                return True
            except LiveJournalError:
                return False

        with ThreadPoolExecutor(max_workers=12) as pool:
            assert sum(pool.map(reserve, range(100))) == 1
        assert journal.verify_audit_chain()
    finally:
        journal.close()
