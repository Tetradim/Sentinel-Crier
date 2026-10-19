"""Cloud-facing, fail-closed brokerage-readiness API.

This service deliberately does not expose live order submission, credential
provisioning or execution ingestion until approved broker adapters and a
per-customer identity provider are integrated. No fake balances or fills.
"""

from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .official_brokers import AlpacaLiveReadOnly, BrokerConnectionError

log = logging.getLogger("crier.cloud")


@dataclass(frozen=True)
class CloudSettings:
    """One-owner development deployment only; not customer multitenancy."""

    # repr=False: a dataclass repr would otherwise print every secret into logs,
    # tracebacks and pytest failure output.
    api_token: str = field(repr=False)
    alpaca_key_id: str | None = field(default=None, repr=False)
    alpaca_secret_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_environment(cls) -> "CloudSettings":
        token = os.environ.get("CRIER_CLOUD_OPERATOR_TOKEN", "")
        if len(token) < 48 or token.strip() != token or token.lower() in {
            "example", "changeme", "secret", "password"
        }:
            raise RuntimeError(
                "CRIER_CLOUD_OPERATOR_TOKEN must be a generated 48+ character secret"
            )
        return cls(api_token=token,
                   alpaca_key_id=os.environ.get('CRIER_ALPACA_LIVE_KEY_ID') or None,
                   alpaca_secret_key=os.environ.get('CRIER_ALPACA_LIVE_SECRET_KEY') or None)


class BrokerReadiness(BaseModel):
    broker_id: str
    name: str
    connection_status: str = "authorization_required"
    live_trading: bool = False
    options_trading: bool = False
    quotes_available: bool = False
    fills_verified: bool = False
    reason: str = "Official customer-facing broker authorization is not configured"


class SystemReadiness(BaseModel):
    ready_for_live_orders: bool = False
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    blocking_reasons: list[str]


def create_cloud_app(settings: CloudSettings | None = None) -> FastAPI:
    settings = settings or CloudSettings.from_environment()
    app = FastAPI(
        title="Sentinel Crier Cloud Gateway",
        version="0.1.0",
        docs_url=None, redoc_url=None, openapi_url=None,
    )

    @app.middleware("http")
    async def harden(request: Request, call_next):
        safe = request.method == "GET" or (request.method == "HEAD" and request.url.path == "/health")
        if not safe:
            return JSONResponse(
                {"detail": "Live order services unavailable until approved and audited"},
                status_code=405,
                headers={"Cache-Control": "no-store"},
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    expected_token = settings.api_token.encode("utf-8")

    def authorize(authorization: str | None = Header(default=None)) -> None:
        # Compare bytes: hmac.compare_digest raises TypeError on non-ASCII str, which
        # would turn a malformed header into an unauthenticated 500.
        scheme, _, supplied = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
                supplied.encode("utf-8", "surrogateescape"), expected_token):
            raise HTTPException(status_code=401, detail="Authorization required",
                                headers={"WWW-Authenticate": "Bearer"})

    @app.api_route("/health", methods=["GET", "HEAD"])
    def health():
        # Liveness only; must never be used as proof of trading readiness.
        return {"service": "crier-cloud", "alive": True}

    @app.get("/v1/readiness", response_model=SystemReadiness,
             dependencies=[Depends(authorize)])
    def readiness():
        return SystemReadiness(blocking_reasons=[
            "Customer identity and brokerage OAuth authorization not configured",
            "Approved Webull Connect and other live broker adapters not configured",
            "Broker-order preview, verification and authoritative fill feeds unavailable",
            "Durable cloud order execution and transactional Discord outbox not activated",
        ])

    @app.get("/v1/brokers", response_model=list[BrokerReadiness],
             dependencies=[Depends(authorize)])
    def brokers():
        # An explicit capability absence, not pretend broker connectivity.
        return [
            BrokerReadiness(broker_id="webull", name="Webull"),
            BrokerReadiness(broker_id="alpaca", name="Alpaca",
                connection_status="configured_unverified" if settings.alpaca_key_id and settings.alpaca_secret_key else "authorization_required",
                reason="Live credentials configured; account connectivity not yet verified" if settings.alpaca_key_id and settings.alpaca_secret_key else "Official customer-facing broker authorization is not configured"),
            BrokerReadiness(broker_id="tradier", name="Tradier"),
        ]

    def alpaca_adapter() -> AlpacaLiveReadOnly:
        if not settings.alpaca_key_id or not settings.alpaca_secret_key:
            raise HTTPException(status_code=503, detail="Live broker authorization unavailable")
        return AlpacaLiveReadOnly(settings.alpaca_key_id, settings.alpaca_secret_key)

    @app.get("/v1/accounts", dependencies=[Depends(authorize)])
    async def accounts():
        broker = alpaca_adapter()
        try:
            account = await broker.account()
        except BrokerConnectionError as exc:
            log.warning("alpaca account read failed: %s", exc)  # message never holds secrets
            raise HTTPException(status_code=503, detail="Live broker account unavailable")
        return {"captured_at": datetime.now(timezone.utc).isoformat(),
                "accounts": [account], "unavailable_brokers": ["webull", "tradier"]}

    @app.get("/v1/positions", dependencies=[Depends(authorize)])
    async def positions():
        broker = alpaca_adapter()
        try:
            account = await broker.account()
            positions = await broker.positions()
        except BrokerConnectionError as exc:
            log.warning("alpaca positions read failed: %s", exc)
            raise HTTPException(status_code=503, detail="Live broker positions unavailable")
        for position in positions:
            position["account_id"] = account["account_id"]
        return {"captured_at": datetime.now(timezone.utc).isoformat(),
                "positions": positions, "unavailable_brokers": ["webull", "tradier"]}

    @app.get("/v1/options", dependencies=[Depends(authorize)])
    def options():
        raise HTTPException(status_code=503, detail="Live options data unavailable")

    @app.get("/v1/orders", dependencies=[Depends(authorize)])
    def orders():
        raise HTTPException(status_code=503, detail="Live order retrieval unavailable")

    return app


def main():
    import uvicorn
    # Only bind loopback: the deployment reverse proxy owns TLS and IP exposure.
    uvicorn.run(create_cloud_app(), host="127.0.0.1", port=8876, access_log=False)


if __name__ == "__main__":
    main()
