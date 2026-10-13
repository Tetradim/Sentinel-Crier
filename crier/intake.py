"""Authenticated fill envelopes and operator-reviewed receipt evidence.

Receipt text is data, never an instruction. Durable acceptance and outbox writes
share one SQLite transaction so a lost HTTP response is safe to retry.
"""
from datetime import timezone
import hashlib
import json
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import Snapshot, Settings, number

CONTRACT_VERSION = "crier.fill.v1"


class IntakeConflict(ValueError):
    pass


class IncomingFill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["crier.fill.v1"]
    event_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$")
    snapshot: Snapshot


class ReceiptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=12000)
    broker: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    environment: Literal["sandbox", "production"] = "sandbox"

    @field_validator("text")
    @classmethod
    def nonempty_text(cls, value):
        value = value.replace("\r\n", "\n").strip()
        if not value:
            raise ValueError("Receipt text must not be empty")
        return value


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: Snapshot


def canonical_snapshot(snapshot):
    data = snapshot.model_dump(mode="json")
    data["cumulative_qty"] = number(snapshot.cumulative_qty)
    data["average_price"] = number(snapshot.average_price)
    data["occurred_at"] = snapshot.occurred_at.astimezone(timezone.utc).isoformat()
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def parse_receipt(text, broker, environment):
    """Prefill only explicit fields from documented key/value receipts."""
    allowed = {"account", "order_id", "symbol", "category", "side", "intent",
               "cumulative_qty", "average_price", "occurred_at", "status"}
    draft = {"broker": broker, "environment": environment}
    warnings, seen = [], set()
    for line in text.splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if sep and key in allowed and value:
            if key in seen:
                draft.pop(key, None)
                warnings.append(f"Repeated {key}; enter it explicitly during review.")
            else:
                draft[key] = value
            seen.add(key)
        else:
            warnings.append("Some receipt text could not be mapped; review every field before publishing.")
    missing = sorted((allowed - {"intent"}) - draft.keys())
    if missing:
        warnings.append("Enter missing fields: " + ", ".join(missing))
    warnings.append("This receipt is not broker-verified. Confirm only an actual fill; use cumulative filled quantity and average fill price.")
    return draft, list(dict.fromkeys(warnings))


def _settings(db):
    row = db.execute("SELECT value FROM config WHERE id='settings'").fetchone()
    return Settings.model_validate_json(row[0]) if row else Settings()


def _receipt(row):
    result = dict(row)
    for key in ("draft", "warnings", "result"):
        result[key] = json.loads(result[key]) if result[key] else None
    result.pop("confirmation", None)
    return result


class Intake:
    def __init__(self, store):
        self.store = store

    def accept(self, event: IncomingFill):
        digest = hashlib.sha256(canonical_snapshot(event.snapshot).encode()).hexdigest()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM incoming_events WHERE id=?", (event.event_id,)).fetchone()
            if previous:
                if previous["digest"] != digest:
                    raise IntakeConflict("Event ID already exists with different data; use a new ID for a correction")
                return json.loads(previous["response"])
            result = self.store.ingest_in_transaction(db, event.snapshot, _settings(db))
            response = {"contract_version": CONTRACT_VERSION, "event_id": event.event_id,
                        "accepted": True, "outcome": result["outcome"],
                        "reference": result["fill"]["reference"] if result["fill"] else None}
            db.execute("INSERT INTO incoming_events VALUES (?,?,?,?)",
                       (event.event_id, digest, time.time(), json.dumps(response)))
            return response

    def capture(self, text, broker, environment):
        value = ReceiptInput(text=text, broker=broker, environment=environment)
        key = hashlib.sha256(json.dumps([value.broker, value.environment, value.text]).encode()).hexdigest()
        draft, warnings = parse_receipt(value.text, value.broker, value.environment)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO receipts(id,created,text,broker,environment,status,draft,warnings) VALUES (?,?,?,?,?,'pending',?,?)",
                       (key, time.time(), value.text, broker, environment, json.dumps(draft), json.dumps(warnings)))
            return _receipt(db.execute("SELECT * FROM receipts WHERE id=?", (key,)).fetchone())

    def list_receipts(self):
        with self.store.connect() as db:
            return [_receipt(r) for r in db.execute("SELECT * FROM receipts ORDER BY created DESC LIMIT 100")]

    def confirm(self, key, snapshot: Snapshot):
        # A caller cannot elevate pasted evidence to broker-reported provenance.
        snapshot = snapshot.model_copy(update={"verification": "user_confirmed", "time_basis": "user_supplied"})
        confirmation = canonical_snapshot(snapshot)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM receipts WHERE id=?", (key,)).fetchone()
            if row is None:
                raise KeyError("Receipt not found")
            if snapshot.broker != row["broker"] or snapshot.environment != row["environment"]:
                raise ValueError("Broker and environment must match the captured receipt")
            if row["status"] == "confirmed" and row["confirmation"] == confirmation:
                return _receipt(row)
            if row["status"] != "pending":
                raise IntakeConflict("Receipt is already resolved; capture new evidence for a correction")
            settings = _settings(db)
            if settings.format == "echo":
                raise ValueError("Choose Homebrew, rich card or plain text before confirming a receipt; Echo requires broker evidence")
            result = self.store.ingest_in_transaction(db, snapshot, settings)
            result = {"outcome": result["outcome"], "reference": result["fill"]["reference"] if result["fill"] else None}
            db.execute("UPDATE receipts SET status='confirmed',confirmation=?,result=? WHERE id=?",
                       (confirmation, json.dumps(result), key))
            db.execute("INSERT INTO audit(time,outcome,data) VALUES (?,?,?)",
                       (time.time(), "receipt_confirmed", json.dumps({"receipt_id": key, **result})))
            return _receipt(db.execute("SELECT * FROM receipts WHERE id=?", (key,)).fetchone())

    def reject(self, key):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM receipts WHERE id=?", (key,)).fetchone()
            if row is None:
                raise KeyError("Receipt not found")
            if row["status"] == "confirmed":
                raise IntakeConflict("A confirmed receipt cannot be rejected after acceptance")
            db.execute("UPDATE receipts SET status='rejected' WHERE id=?", (key,))
            if row["status"] != "rejected":
                db.execute("INSERT INTO audit(time,outcome,data) VALUES (?,?,?)",
                           (time.time(), "receipt_rejected", json.dumps({"receipt_id": key})))
            return _receipt(db.execute("SELECT * FROM receipts WHERE id=?", (key,)).fetchone())
