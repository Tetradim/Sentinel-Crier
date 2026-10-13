import pytest
from fastapi.testclient import TestClient
from crier.app import create_app
from crier.config import Config

TOKEN = "a" * 32
KEY = "b" * 32
AUTH = {"Authorization": "Bearer " + TOKEN}
SNAPSHOT = dict(broker="robinhood", account="private-desk", order_id="order-1", symbol="AAPL",
    category="US_STOCK", side="BUY", cumulative_qty="2", average_price="100",
    occurred_at="2026-10-13T14:42:18Z", status="FILLED", environment="sandbox")


def client(tmp_path, **options):
    return TestClient(create_app(Config(data_dir=tmp_path, token=TOKEN, **options)))


def test_intake_disabled_and_not_authenticated_by_console_token(tmp_path):
    with client(tmp_path) as c:
        assert c.post("/api/intake/fills", headers=AUTH, json={"event_id":"one", "snapshot":SNAPSHOT}).status_code == 503
    with client(tmp_path, intake_key=KEY, intake_verified=True) as c:
        assert c.post("/api/intake/fills", headers=AUTH, json={"event_id":"one", "snapshot":SNAPSHOT}).status_code == 401


def test_versioned_intake_idempotency_and_schema(tmp_path):
    with client(tmp_path, intake_key=KEY, intake_verified=True) as c:
        headers = {"X-API-Key": KEY, "Idempotency-Key": "one"}
        event = {"contract_version": "crier.fill.v1", "event_id": "one", "snapshot": SNAPSHOT}
        first = c.post("/api/intake/fills", headers=headers, json=event)
        assert first.status_code == 200 and first.json()["outcome"] == "queued"
        assert c.post("/api/intake/fills", headers=headers, json=event).json() == first.json()
        changed = {**event, "snapshot": {**SNAPSHOT, "average_price": "101"}}
        assert c.post("/api/intake/fills", headers=headers, json=changed).status_code == 409
        assert c.post("/api/intake/fills", headers={**headers, "Idempotency-Key": "other"}, json=event).status_code == 409
        assert c.post("/api/intake/fills", headers=headers, json={**event, "contract_version":"bad"}).status_code == 422
        assert c.post("/api/intake/fills", headers=headers, json={"event_id":"one", "snapshot":SNAPSHOT}).status_code == 422
        schema = c.get("/api/intake/schema", headers=headers)
        assert schema.status_code == 200 and schema.json()["contract_version"] == "crier.fill.v1"
        assert KEY not in schema.text
        assert len(c.get("/api/history", headers=AUTH).json()) == 1


def test_unverified_intake_can_discover_but_not_enqueue(tmp_path):
    with client(tmp_path, intake_key=KEY) as c:
        assert c.get("/api/intake/schema", headers={"X-API-Key":KEY}).status_code == 200
        assert c.post("/api/intake/fills", headers={"X-API-Key":KEY}, json={"contract_version":"crier.fill.v1", "event_id":"one", "snapshot":SNAPSHOT}).status_code == 503
        assert c.get("/api/history", headers=AUTH).json() == []


def test_receipt_flow_requires_explicit_confirmation_and_labels_source(tmp_path):
    with client(tmp_path) as c:
        receipt = {"text":"AAPL bought", "broker":"robinhood", "environment":"sandbox"}
        assert c.post("/api/receipts", json=receipt).status_code == 401
        row = c.post("/api/receipts", headers=AUTH, json=receipt).json()
        assert row["status"] == "pending"
        assert c.get("/api/history", headers=AUTH).json() == []
        assert c.post(f"/api/receipts/{row['id']}/confirm", headers=AUTH, json={"snapshot":{**SNAPSHOT,"occurred_at":"missing"}}).status_code == 422
        path = f"/api/receipts/{row['id']}/confirm"
        confirmed = c.post(path, headers=AUTH, json={"snapshot": SNAPSHOT})
        assert confirmed.status_code == 200 and confirmed.json()["result"]["outcome"] == "queued"
        assert c.post(path, headers=AUTH, json={"snapshot": SNAPSHOT}).json() == confirmed.json()
        history = c.get("/api/history", headers=AUTH).json()
        assert len(history) == 1 and "User-confirmed" in history[0]["payload"]["content"]
        assert c.get("/api/status", headers=AUTH).json()["mode"] == "preview"
        assert c.post(f"/api/receipts/{row['id']}/reject", headers=AUTH, json={}).status_code == 409
        assert c.post("/api/receipts/unknown/reject", headers=AUTH, json={}).status_code == 404


def test_capabilities_and_validation_do_not_leak_private_input(tmp_path):
    with client(tmp_path) as c:
        cap = c.get("/api/capabilities", headers=AUTH).json()
        assert next(b for b in cap["brokers"] if b["id"] == "robinhood")["mode"] == "manual_receipt"
        r = c.post("/api/receipts", headers=AUTH, json={"text":"PRIVATE-RECEIPT", "broker":"PRIVATE-INVALID-BROKER"})
        assert r.status_code == 422
        assert "PRIVATE-" not in r.text


def test_publisher_enable_is_not_tied_to_webull(tmp_path):
    config = Config(data_dir=tmp_path, token=TOKEN, publisher_verified=True,
                    delivery_enabled=True, webhook="https://discord.com/api/webhooks/123/token")
    assert config.delivery_enabled and not config.webull_verified
    with pytest.raises(ValueError): Config(data_dir=tmp_path, token=TOKEN, monitor="robinhood")


def test_selected_monitor_lifecycle_is_owned_by_console(tmp_path, monkeypatch):
    import crier.app as app_module
    events = []
    class FakeMonitor:
        def is_alive(self): return True
    def start(config):
        events.append(("start",config.monitor))
        return FakeMonitor()
    monkeypatch.setattr(app_module, "start_monitor", start)
    monkeypatch.setattr(app_module, "stop_monitor", lambda process: events.append(("stop",process.is_alive())))
    with client(tmp_path, monitor="webull") as c:
        state = c.get("/api/status",headers=AUTH).json()
        assert state["monitor"] == {"selected":"webull", "running":True}
    assert events == [("start","webull"),("stop",True)]
