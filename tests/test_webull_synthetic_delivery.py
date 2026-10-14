"""Synthetic Webull API fill -> durable outbox -> fake Discord delivery.

No live brokerage or Discord credentials are used.
"""
import httpx

from crier.intake import IncomingFill, Intake
from crier.models import Snapshot
from crier.store import Store
from crier.delivery import deliver_once


def test_synthetic_webull_option_fill_to_discord_once(tmp_path):
    store = Store(tmp_path / "webull-demo.sqlite3")
    intake = Intake(store)
    snapshot = Snapshot(
        broker="webull", environment="sandbox", account="synthetic-account",
        order_id="synthetic-order-001", symbol="SPY261016C00600000",
        category="US_OPTION", side="BUY", intent="OPEN",
        cumulative_qty="2", average_price="1.25",
        occurred_at="2026-10-13T14:42:18Z", status="FILLED",
        verification="broker_reported", time_basis="execution",
    )
    event = IncomingFill(contract_version="crier.fill.v1",
                         event_id="synthetic:webull:001", snapshot=snapshot)
    accepted = intake.accept(event)
    assert accepted["outcome"] == "queued"
    assert intake.accept(event) == accepted

    sent = []
    def fake_discord(request):
        sent.append(request)
        assert request.url.host == "discord.com"
        assert request.url.params["wait"] == "true"
        assert "synthetic-account" not in request.content.decode()
        assert "synthetic-order-001" not in request.content.decode()
        return httpx.Response(200, json={"id": "123456789"})

    with httpx.Client(transport=httpx.MockTransport(fake_discord)) as client:
        assert deliver_once(store, "https://discord.com/api/webhooks/123/token", client)
        assert not deliver_once(store, "https://discord.com/api/webhooks/123/token", client)

    assert len(sent) == 1
    assert store.history()[0]["status"] == "sent"
    assert store.history()[0]["message_id"] == "123456789"
