"""Screen evidence must never enter the Discord outbox without independent review."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from crier.screen_observations import screen_observation_router
from crier.store import Store
from fastapi import FastAPI


def test_screen_observation_is_quarantined_and_idempotent():
    with TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "crier.db")
        app = FastAPI()
        app.include_router(screen_observation_router(store, lambda: None, "u" * 40))
        client = TestClient(app)
        evidence = {
            "schema": "crier.screen-observation.v1",
            "source": "ios-replaykit-vision", "broker": "WEBULL",
            "symbol": "SPY", "expiration": "2026-10-16",
            "right": "C", "strike": "600", "side": "BUY",
            "quantity": 4, "fillPrice": "1.25",
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "evidenceId": "a7a5eae0-b1d2-4e3c-b4c5-f99979c45d23",
        }
        first = client.post("/api/screen-observations", headers={"Authorization": "Bearer " + "u" * 40}, json=evidence)
        assert first.status_code == 202, first.text
        assert first.json()["discord_published"] is False
        assert client.post("/api/screen-observations", headers={"Authorization": "Bearer " + "u" * 40}, json=evidence).status_code == 202
        rows = client.get("/api/screen-observations", headers={"Authorization": "Bearer " + "a" * 32}).json()
        assert len(rows) == 1
        assert rows[0]["status"] == "pending_review"
        assert store.history() == []
        changed = {**evidence, "quantity": 5}
        assert client.post("/api/screen-observations", headers={"Authorization": "Bearer " + "u" * 40}, json=changed).status_code == 409


def test_screen_observation_rejects_invalid_broker_and_price():
    with TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "crier.db")
        app = FastAPI()
        app.include_router(screen_observation_router(store, lambda: None, "u" * 40))
        client = TestClient(app)
        evidence = {
            "schema": "crier.screen-observation.v1",
            "source": "ios-replaykit-vision", "broker": "UNKNOWN",
            "symbol": "SPY", "expiration": "2026-10-16",
            "right": "C", "strike": "600", "side": "BUY",
            "quantity": 4, "fillPrice": "NaN",
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "evidenceId": "a7a5eae0-b1d2-4e3c-b4c5-f99979c45d23",
        }
        assert client.post("/api/screen-observations", headers={"Authorization": "Bearer " + "u" * 40}, json=evidence).status_code == 422

def test_screen_upload_authentication_is_separate_from_admin():
    with TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "crier.db")
        app = FastAPI()
        app.include_router(screen_observation_router(store, lambda: None, "u" * 40))
        client = TestClient(app)
        assert client.post("/api/screen-observations", json={}).status_code == 401
        assert client.post("/api/screen-observations",
                           headers={"Authorization": "Bearer wrong"}, json={}).status_code == 401
