"""Regression: a manual receipt must not permanently block later broker fills."""
from datetime import datetime, timezone
from decimal import Decimal

from crier.models import Settings, Snapshot
from crier.store import Store


def test_manual_receipt_reconciles_identical_broker_fill_then_increment(tmp_path):
    store = Store(tmp_path / "reconcile.sqlite")
    base = dict(
        broker="webull", environment="sandbox", account="demo",
        order_id="same-order", symbol="SPY", category="US_STOCK",
        side="BUY", intent="OPEN", cumulative_qty=Decimal("1"),
        average_price=Decimal("10"), occurred_at=datetime.now(timezone.utc),
        status="PARTIAL",
    )
    manual = Snapshot(**base, verification="user_confirmed")
    broker = Snapshot(**base, verification="broker_reported")
    later = broker.model_copy(update={
        "cumulative_qty": Decimal("2"),
        "average_price": Decimal("11"),
        "status": "FILLED",
    })
    assert store.ingest(manual, Settings())["outcome"] == "queued"
    reconciled = store.ingest(broker, Settings())
    assert reconciled["outcome"] == "reconciled"
    assert reconciled["fill"] is None
    increment = store.ingest(later, Settings())
    assert increment["outcome"] == "queued"
    assert increment["fill"]["quantity"] == "1"
    assert len(store.history()) == 2


def test_conflicting_broker_receipt_remains_in_review(tmp_path):
    store = Store(tmp_path / "conflict.sqlite")
    base = dict(
        account="demo", order_id="conflict", symbol="SPY",
        category="US_STOCK", side="BUY", intent="OPEN",
        cumulative_qty=Decimal("1"), average_price=Decimal("10"),
        occurred_at=datetime.now(timezone.utc), status="FILLED",
    )
    assert store.ingest(Snapshot(**base, verification="user_confirmed"), Settings())["outcome"] == "queued"
    conflicting = Snapshot(**(base | {"average_price": Decimal("12")}), verification="broker_reported")
    assert store.ingest(conflicting, Settings())["outcome"] == "review"
