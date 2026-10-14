"""Release-gate checks for screen observations: no unauthenticated reads or publishing."""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from crier.screen_observations import screen_observation_router
from crier.store import Store


def make_client(tmp_path):
    store = Store(Path(tmp_path) / "gate.sqlite3")
    app = FastAPI()

    def admin(authorization: str = __import__("fastapi").Header(default="")):
        from fastapi import HTTPException
        if authorization != "Bearer " + "a" * 40:
            raise HTTPException(401)

    app.include_router(screen_observation_router(store, admin, "u" * 40))
    return TestClient(app), store


def evidence():
    return {
        "schema": "crier.screen-observation.v1",
        "source": "ios-replaykit-vision",
        "broker": "WEBULL",
        "symbol": "SPY",
        "expiration": "2026-10-16",
        "right": "C",
        "strike": "600",
        "side": "BUY",
        "quantity": 4,
        "fillPrice": "1.25",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "evidenceId": "b7a5eae0-b1d2-4e3c-b4c5-f99979c45d23",
    }


def test_upload_and_read_have_separate_credentials(tmp_path):
    client, store = make_client(tmp_path)
    upload = {"Authorization": "Bearer " + "u" * 40}
    admin = {"Authorization": "Bearer " + "a" * 40}
    assert client.post("/api/screen-observations", json=evidence()).status_code == 401
    assert client.post("/api/screen-observations", headers=admin, json=evidence()).status_code == 401
    assert client.post("/api/screen-observations", headers=upload, json=evidence()).status_code == 202
    assert client.get("/api/screen-observations", headers=upload).status_code == 401
    assert client.get("/api/screen-observations").status_code == 401
    result = client.get("/api/screen-observations", headers=admin)
    assert result.status_code == 200
    assert result.json()[0]["evidence"]["symbol"] == "SPY"
    assert result.json()[0]["status"] == "pending_review"
    assert store.history() == []


def test_replayed_evidence_cannot_create_delivery(tmp_path):
    client, store = make_client(tmp_path)
    upload = {"Authorization": "Bearer " + "u" * 40}
    original = evidence()
    for _ in range(3):
        assert client.post("/api/screen-observations", headers=upload, json=original).status_code == 202
    assert store.history() == []
    rows = client.get("/api/screen-observations",
                      headers={"Authorization": "Bearer " + "a" * 40}).json()
    assert len(rows) == 1


def test_invalid_timestamp_is_rejected(tmp_path):
    client, store = make_client(tmp_path)
    bad = evidence()
    bad["observedAt"] = "2026-10-14T10:00:00"
    assert client.post("/api/screen-observations",
                       headers={"Authorization": "Bearer " + "u" * 40}, json=bad).status_code == 422
    assert store.history() == []
