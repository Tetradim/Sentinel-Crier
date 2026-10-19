"""Offline transport contract verification; no customer-facing mock trading."""
import asyncio
import httpx
import pytest

from crier.official_brokers import (
    AlpacaLiveReadOnly, BrokerConnectionError, ALPACA_PRODUCTION_ORIGIN
)


def test_live_alpaca_account_uses_official_host_and_auth_headers():
    requested = []

    def response(request):
        requested.append(request)
        assert request.url.scheme == "https"
        assert request.url.host == "api.alpaca.markets"
        assert request.url.path == "/v2/account"
        assert request.headers["APCA-API-KEY-ID"] == "key-id"
        assert request.headers["APCA-API-SECRET-KEY"] == "secret"
        return httpx.Response(200, json={
            "id": "live-account", "currency": "USD", "equity": "4300.00",
            "buying_power": "1200.00", "status": "ACTIVE",
        })

    adapter = AlpacaLiveReadOnly("key-id", "secret",
                                  transport=httpx.MockTransport(response))
    result = asyncio.run(adapter.account())
    assert result["equity"] == "4300.00"
    assert result["buying_power"] == "1200.00"
    assert len(requested) == 1


def test_broker_missing_amount_remains_unknown():
    def response(request):
        return httpx.Response(200, json={"id": "live-account", "currency": "USD"})
    adapter = AlpacaLiveReadOnly("key-id", "secret",
                                  transport=httpx.MockTransport(response))
    result = asyncio.run(adapter.account())
    assert result["equity"] is None
    assert result["buying_power"] is None


def test_invalid_account_response_fails_closed():
    def response(request):
        return httpx.Response(200, json={"id": "live-account", "equity": "NaN"})
    adapter = AlpacaLiveReadOnly("key-id", "secret",
                                  transport=httpx.MockTransport(response))
    with pytest.raises(BrokerConnectionError):
        asyncio.run(adapter.account())


def test_positions_normalize_list_only():
    def response(request):
        assert request.url.path == "/v2/positions"
        return httpx.Response(200, json=[{
            "symbol": "SPY261016C00750000", "asset_id": "contract-1",
            "qty": "2", "avg_entry_price": "0.60", "market_value": "125.0"
        }])
    adapter = AlpacaLiveReadOnly("key-id", "secret",
                                  transport=httpx.MockTransport(response))
    result = asyncio.run(adapter.positions())
    assert len(result) == 1
    assert result[0]["quantity"] == "2"
    assert result[0]["symbol"] == "SPY261016C00750000"


def test_positions_reject_unexpected_shape():
    def response(request):
        return httpx.Response(200, json={"positions": []})
    adapter = AlpacaLiveReadOnly("key-id", "secret",
                                  transport=httpx.MockTransport(response))
    with pytest.raises(BrokerConnectionError):
        asyncio.run(adapter.positions())


def test_no_redirect_to_untrusted_host():
    def response(request):
        return httpx.Response(302, headers={"Location": "https://evil.invalid/token"})
    adapter = AlpacaLiveReadOnly("key-id", "secret",
                                  transport=httpx.MockTransport(response))
    with pytest.raises(BrokerConnectionError):
        asyncio.run(adapter.account())


def test_missing_currency_is_never_assumed_to_be_usd():
    def response(request):
        return httpx.Response(200, json={"id": "live-account", "equity": "10"})
    adapter = AlpacaLiveReadOnly("key-id", "secret",
                                  transport=httpx.MockTransport(response))
    with pytest.raises(BrokerConnectionError):
        asyncio.run(adapter.account())


def test_account_payload_matches_the_client_contract():
    def response(request):
        return httpx.Response(200, json={"id": "a1", "currency": "USD", "equity": "1"})
    adapter = AlpacaLiveReadOnly("key-id", "secret",
                                  transport=httpx.MockTransport(response))
    assert set(asyncio.run(adapter.account())) == {
        "broker_id", "account_id", "display_name", "currency", "equity",
        "buying_power", "status"}


@pytest.mark.parametrize("status", [401, 429, 503])
def test_error_names_the_http_status_but_never_a_secret(status):
    def response(request):
        return httpx.Response(status, text="secret-body")
    adapter = AlpacaLiveReadOnly("key-id", "very-secret",
                                  transport=httpx.MockTransport(response))
    with pytest.raises(BrokerConnectionError) as caught:
        asyncio.run(adapter.account())
    message = str(caught.value)
    assert f"HTTP {status}" in message
    assert "very-secret" not in message and "key-id" not in message and "secret-body" not in message
