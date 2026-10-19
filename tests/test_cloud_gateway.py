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


def test_malformed_or_non_ascii_authorization_is_401_not_500():
    app = create_cloud_app(CloudSettings(api_token=TOKEN))
    client = TestClient(app, raise_server_exceptions=False)
    for header in ("Bearer caf\u00e9".encode("latin-1"), b"Bearer", b"Basic abc", b"", b"Bearer  " + TOKEN.encode()):
        response = client.get("/v1/readiness", headers={"Authorization": header})
        assert response.status_code == 401


def test_bearer_scheme_is_case_insensitive(client):
    assert client.get("/v1/readiness", headers={"Authorization": f"bearer {TOKEN}"}).status_code == 200


def test_head_health_is_allowed_but_other_methods_are_not(client):
    assert client.head("/health").status_code == 200
    assert client.head("/v1/readiness").status_code == 405
    assert client.put("/health").status_code == 405


def test_settings_repr_never_prints_a_secret():
    text = repr(CloudSettings(api_token=TOKEN, alpaca_key_id="KEYID1", alpaca_secret_key="SECRET1"))
    assert TOKEN not in text and "KEYID1" not in text and "SECRET1" not in text


def _gateway_with_alpaca(monkeypatch, handler):
    import httpx
    from crier import cloud_gateway
    from crier.official_brokers import AlpacaLiveReadOnly
    monkeypatch.setattr(cloud_gateway, "AlpacaLiveReadOnly", lambda key, secret: AlpacaLiveReadOnly(
        key, secret, transport=httpx.MockTransport(handler)))
    return TestClient(create_cloud_app(CloudSettings(
        api_token=TOKEN, alpaca_key_id="KEYID1", alpaca_secret_key="SECRET1")))


def test_accounts_payload_has_the_fields_the_ios_client_requires(monkeypatch):
    import httpx
    client = _gateway_with_alpaca(monkeypatch, lambda request: httpx.Response(
        200, json={"id": "a1", "currency": "USD", "equity": "4300.00", "buying_power": "1200.00",
                   "status": "ACTIVE"}))
    body = client.get("/v1/accounts", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    account = body["accounts"][0]
    # Swift LiveAccount: brokerId, accountId, displayName, currency, buyingPower, equity
    assert {"broker_id", "account_id", "display_name", "currency", "buying_power", "equity"} <= set(account)
    assert isinstance(account["equity"], str)  # money stays a string end to end


def test_upstream_failure_is_503_and_logged_without_secrets(monkeypatch, caplog):
    import httpx
    client = _gateway_with_alpaca(monkeypatch, lambda request: httpx.Response(401))
    with caplog.at_level("WARNING", logger="crier.cloud"):
        response = client.get("/v1/accounts", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503
    assert "HTTP 401" in caplog.text
    assert "SECRET1" not in caplog.text and TOKEN not in caplog.text
