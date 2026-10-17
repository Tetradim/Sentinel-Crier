"""Security and fail-closed cloud gateway checks; no brokerage connections."""
import pytest
from fastapi.testclient import TestClient
from crier.cloud_gateway import CloudSettings, create_cloud_app

TOKEN = "4xPVQ2fwO7x3NdVSB5QLvuP4CQfrhj2fm2dq90W3WgTz1t5H"


@pytest.fixture
def client():
    return TestClient(create_cloud_app(CloudSettings(api_token=TOKEN)))


def test_health_not_trading_readiness(client):
    assert client.get("/health").json() == {"service": "crier-cloud", "alive": True}
    assert client.get("/v1/readiness").status_code == 401


def test_readiness_auth_and_default_live_disabled(client):
    assert client.get("/v1/readiness",
                      headers={"Authorization": "Bearer bad"}).status_code == 401
    response = client.get("/v1/readiness", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.json()["ready_for_live_orders"] is False
    assert response.json()["blocking_reasons"]
    assert response.headers["Cache-Control"] == "no-store"


def test_every_broker_fails_closed(client):
    response = client.get("/v1/brokers", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    rows = response.json()
    assert {row["broker_id"] for row in rows} == {"webull", "alpaca", "tradier"}
    assert all(not row["live_trading"] and not row["fills_verified"]
               for row in rows)


def test_no_invented_accounts_quotes_positions(client):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    for path in ("/v1/accounts", "/v1/positions", "/v1/options", "/v1/orders"):
        assert client.get(path, headers=headers).status_code == 503


def test_no_order_mutation_endpoint(client):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    for path in ("/v1/orders", "/v1/orders/abc/cancel", "/v1/orders/preview",
                 "/v1/brokers/connect"):
        response = client.post(path, headers=headers, json={"contracts": 10})
        assert response.status_code == 405


def test_cloud_secret_required_at_startup(monkeypatch):
    monkeypatch.delenv("CRIER_CLOUD_OPERATOR_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        CloudSettings.from_environment()
    monkeypatch.setenv("CRIER_CLOUD_OPERATOR_TOKEN", "changeme")
    with pytest.raises(RuntimeError):
        CloudSettings.from_environment()
