"""Quarantined, authenticated screen observations. Never feed OCR into fill intake."""
import json
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScreenObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_: Literal["crier.screen-observation.v1"] = Field(alias="schema")
    source: Literal["ios-replaykit-vision"]
    broker: Literal["WEBULL"]
    symbol: str = Field(pattern=r"^[A-Z]{1,6}$")
    expiration: str
    right: Literal["C", "P"]
    strike: str
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0, le=100000)
    fillPrice: str
    observedAt: datetime
    evidenceId: UUID

    @field_validator("expiration")
    @classmethod
    def valid_expiration(cls, value):
        from datetime import date
        date.fromisoformat(value)
        return value

    @field_validator("strike", "fillPrice")
    @classmethod
    def positive_decimal(cls, value):
        try:
            number = Decimal(value)
            if not number.is_finite() or number <= 0:
                raise ValueError("Must be positive and finite")
        except InvalidOperation as exc:
            raise ValueError("Invalid decimal") from exc
        return value


def screen_observation_router(store, auth):
    router = APIRouter(prefix="/api", dependencies=[Depends(auth)])

    @router.post("/screen-observations", status_code=202)
    def capture(value: ScreenObservation):
        payload = value.model_dump(mode="json", by_alias=True)
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS screen_observations
                       (id TEXT PRIMARY KEY, received REAL NOT NULL, evidence TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending_review')""")
            key = str(value.evidenceId)
            existing = db.execute("SELECT evidence FROM screen_observations WHERE id=?", (key,)).fetchone()
            serialized = json.dumps(payload, sort_keys=True)
            if existing and existing["evidence"] != serialized:
                from fastapi import HTTPException
                raise HTTPException(409, "Evidence ID already used with different content")
            if not existing:
                db.execute("INSERT INTO screen_observations(id,received,evidence) VALUES (?,?,?)",
                           (key, time.time(), serialized))
        return {"accepted": True, "status": "pending_review", "evidence_id": key,
                "discord_published": False}

    @router.get("/screen-observations")
    def list_observations():
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS screen_observations
                       (id TEXT PRIMARY KEY, received REAL NOT NULL, evidence TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending_review')""")
            rows = db.execute("SELECT id,received,evidence,status FROM screen_observations ORDER BY received DESC LIMIT 100")
            return [{"id": row["id"], "received": row["received"],
                     "evidence": json.loads(row["evidence"]), "status": row["status"]} for row in rows]

    return router
