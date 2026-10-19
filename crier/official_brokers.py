"""Official, read-only production Alpaca integration for operator verification.

This adapter cannot submit/cancel orders and contains no paper environment.
It is deliberately not a customer OAuth integration; server-side live credentials
are for the account holder's own initial connectivity checks only.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

ALPACA_PRODUCTION_ORIGIN = "https://api.alpaca.markets"


class BrokerConnectionError(RuntimeError):
    pass


def _money(value: Any) -> str | None:
    """Normalize broker account strings without silently inventing zero."""
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BrokerConnectionError("invalid monetary value from brokerage") from exc
    if not parsed.is_finite():
        raise BrokerConnectionError("nonfinite monetary value from brokerage")
    return str(parsed)


class AlpacaLiveReadOnly:
    def __init__(self, key_id: str, secret_key: str,
                 transport: httpx.AsyncBaseTransport | None = None):
        if not key_id or not secret_key:
            raise BrokerConnectionError("Alpaca production credentials are absent")
        self._key_id = key_id
        self._secret_key = secret_key
        self._transport = transport

    async def _get(self, path: str, expect: type) -> Any:
        """One read-only GET against the production origin; ``expect`` is dict or list."""
        if not path.startswith("/v2/") or "?" in path:
            raise BrokerConnectionError("invalid Alpaca route")
        headers = {
            "APCA-API-KEY-ID": self._key_id,
            "APCA-API-SECRET-KEY": self._secret_key,
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(base_url=ALPACA_PRODUCTION_ORIGIN,
                                      transport=self._transport, timeout=6.0,
                                      follow_redirects=False,
                                      trust_env=False) as client:
            try:
                response = await client.get(path, headers=headers)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as exc:
                # The status code (401 rotated key, 429 throttled, 5xx outage) is what an
                # operator needs; headers and bodies are deliberately not included.
                raise BrokerConnectionError(
                    f"Alpaca {path} returned HTTP {exc.response.status_code}") from exc
            except (httpx.HTTPError, ValueError) as exc:
                raise BrokerConnectionError(
                    f"Alpaca {path} request failed: {type(exc).__name__}") from exc
        if not isinstance(payload, expect):
            raise BrokerConnectionError(f"malformed Alpaca {path} response")
        return payload

    async def account(self) -> dict:
        result = await self._get("/v2/account", dict)
        account_id = result.get("id")
        if not isinstance(account_id, str) or not account_id:
            raise BrokerConnectionError("Alpaca account identity missing")
        currency = result.get("currency")
        if not isinstance(currency, str) or not currency:
            # Never assume USD: an unknown currency must stay unknown, or fail.
            raise BrokerConnectionError("Alpaca account currency missing")
        return {
            "broker_id": "alpaca",
            "account_id": account_id,
            "display_name": "Alpaca",
            "currency": currency,
            "equity": _money(result.get("equity")),
            "buying_power": _money(result.get("buying_power")),
            "status": result.get("status", "unknown"),
        }

    async def positions(self) -> list[dict]:
        payload = await self._get("/v2/positions", list)
        normalized = []
        for item in payload:
            if not isinstance(item, dict) or not item.get("symbol"):
                raise BrokerConnectionError("malformed Alpaca position")
            normalized.append({
                "broker_id": "alpaca",
                "account_id": item.get("account_id"),
                "instrument_id": str(item.get("asset_id", "")),
                "symbol": str(item["symbol"]),
                "quantity": _money(item.get("qty")),
                "market_value": _money(item.get("market_value")),
                "average_entry_price": _money(item.get("avg_entry_price")),
            })
        return normalized
