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
        return httpx.Response(200, json={"id": "live-account"})
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
