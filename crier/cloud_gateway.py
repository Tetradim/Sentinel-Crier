"""Cloud-facing, fail-closed brokerage-readiness API.

This service deliberately does not expose live order submission, credential
provisioning or execution ingestion until approved broker adapters and a
per-customer identity provider are integrated. No fake balances or fills.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class CloudSettings:
    """One-owner development deployment only; not customer multitenancy."""

    api_token: str

    @classmethod
    def from_environment(cls) -> "CloudSettings":
        token = os.environ.get("CRIER_CLOUD_OPERATOR_TOKEN", "")
        if len(token) < 48 or token.strip() != token or token.lower() in {
            "example", "changeme", "secret", "password"
        }:
            raise RuntimeError(
                "CRIER_CLOUD_OPERATOR_TOKEN must be a generated 48+ character secret"
            )
        return cls(api_token=token)


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
        if request.url.path != "/health" and request.method != "GET":
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

    def authorize(authorization: str | None = Header(default=None)) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Authorization required",
                                headers={"WWW-Authenticate": "Bearer"})
        supplied = authorization.removeprefix("Bearer ")
        if not hmac.compare_digest(supplied, settings.api_token):
            raise HTTPException(status_code=401, detail="Authorization required",
                                headers={"WWW-Authenticate": "Bearer"})

    @app.get("/health")
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
            BrokerReadiness(broker_id="alpaca", name="Alpaca"),
            BrokerReadiness(broker_id="tradier", name="Tradier"),
        ]

    @app.get("/v1/accounts", dependencies=[Depends(authorize)])
    def accounts():
        # 503, not 200 []: an unconfigured integration is not an empty account.
        raise HTTPException(status_code=503, detail="Broker authorization unavailable")

    @app.get("/v1/positions", dependencies=[Depends(authorize)])
    def positions():
        raise HTTPException(status_code=503, detail="Broker position retrieval unavailable")

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
