"""Durable live-order intent, broker reconciliation and audit ledger.

This module NEVER connects to a broker or submits orders. Callers must enforce
authenticated customer authorization, broker-side idempotency, and live broker
order permission checks before adding any execution gateway.

A broker timeout is UNKNOWN, not REJECTED. Never blindly retry submission.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any
from uuid import UUID
from datetime import datetime, timezone


ALLOWED_ACTIONS = frozenset({"buyToOpen", "sellToClose", "sellToOpen", "buyToClose"})
BROKER_STATES = frozenset({
    "unsubmitted", "submission_unknown", "accepted", "partially_filled",
    "filled", "canceled", "rejected",
})
FINAL_STATES = frozenset({"filled", "canceled", "rejected"})


class LiveJournalError(ValueError):
    """Unsafe lifecycle transition or malformed order record."""


@dataclass(frozen=True)
class OrderIntent:
    tenant_id: str
    group_id: str
    broker_id: str
    account_id: str
    contract_id: str
    client_order_id: str
    action: str
    quantity: int
    limit_price: str

    def validate(self) -> None:
        for value in (self.tenant_id, self.group_id, self.broker_id,
                      self.account_id, self.contract_id, self.client_order_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 160:
                raise LiveJournalError("missing or oversized identifier")
        try:
            UUID(self.group_id)
            UUID(self.client_order_id)
        except (ValueError, AttributeError) as exc:
            raise LiveJournalError("group and client order IDs must be UUIDs") from exc
        if self.action not in ALLOWED_ACTIONS:
            raise LiveJournalError("unknown order action")
        if type(self.quantity) is not int or not 1 <= self.quantity <= 100000:
            raise LiveJournalError("invalid contracts")
        try:
            price = Decimal(self.limit_price)
        except (InvalidOperation, TypeError) as exc:
            raise LiveJournalError("invalid limit price") from exc
        if not price.is_finite() or price <= 0:
            raise LiveJournalError("limit price must be positive and finite")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class LiveOrderJournal:
    """Transactional SQLite record for one deployment; NOT a public API.

    Each method takes a tenant scope and never returns data from another tenant.
    Multi-instance deployments need a centralized transactional database rather
    than SQLite on independent application hosts.
    """

    def __init__(self, db_path: str | Path):
        self._lock = RLock()
        self._db = sqlite3.connect(str(db_path), isolation_level=None,
                                   check_same_thread=False, timeout=20)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=20000")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS groups (
                tenant_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                confirmed_at TEXT,
                PRIMARY KEY (tenant_id, group_id)
            );
            CREATE TABLE IF NOT EXISTS orders (
                tenant_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                client_order_id TEXT NOT NULL,
                broker_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                contract_id TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                limit_price TEXT NOT NULL,
                state TEXT NOT NULL,
                broker_order_id TEXT,
                cumulative_filled INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (tenant_id, client_order_id),
                FOREIGN KEY (tenant_id, group_id)
                    REFERENCES groups(tenant_id, group_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_account_per_group
                ON orders(tenant_id, group_id, broker_id, account_id);
            CREATE TABLE IF NOT EXISTS executions (
                tenant_id TEXT NOT NULL,
                broker_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                execution_id TEXT NOT NULL,
                client_order_id TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                price TEXT NOT NULL,
                executed_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, broker_id, account_id, execution_id),
                FOREIGN KEY (tenant_id, client_order_id)
                    REFERENCES orders(tenant_id, client_order_id)
            );
            CREATE TABLE IF NOT EXISTS audit (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                event TEXT NOT NULL,
                details TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL
            );
        """)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _audit(self, tenant: str, event: str, details: dict[str, Any]) -> None:
        previous = self._db.execute(
            "SELECT entry_hash FROM audit ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["entry_hash"] if previous else "GENESIS"
        at = _utc()
        payload = json.dumps(details, sort_keys=True, separators=(",", ":"))
        digest = sha256(json.dumps(
            [at, tenant, event, payload, previous_hash],
            separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        self._db.execute(
            "INSERT INTO audit(at,tenant_id,event,details,previous_hash,entry_hash)"
            " VALUES(?,?,?,?,?,?)",
            (at, tenant, event, payload, previous_hash, digest)
        )

    def _begin(self) -> None:
        self._db.execute("BEGIN IMMEDIATE")

    def stage_group(self, intents: list[OrderIntent]) -> None:
        """Stage exact independently validated broker requests without submitting.

        A group must be persisted before any confirmation is presented.
        """
        if not intents:
            raise LiveJournalError("empty order group")
        for intent in intents:
            intent.validate()
        tenant, group = intents[0].tenant_id, intents[0].group_id
        if any((x.tenant_id, x.group_id) != (tenant, group) for x in intents):
            raise LiveJournalError("group scope mismatch")
        if len({(x.broker_id, x.account_id) for x in intents}) != len(intents):
            raise LiveJournalError("duplicate brokerage account in group")
        if len({x.client_order_id for x in intents}) != len(intents):
            raise LiveJournalError("duplicate client order ID")
        with self._lock:
            self._begin()
            try:
                self._db.execute(
                    "INSERT INTO groups(tenant_id,group_id,created_at) VALUES(?,?,?)",
                    (tenant, group, _utc()))
                for x in intents:
                    self._db.execute(
                        "INSERT INTO orders(tenant_id,group_id,client_order_id,broker_id,"
                        "account_id,contract_id,action,quantity,limit_price,state)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (tenant, group, x.client_order_id, x.broker_id, x.account_id,
                         x.contract_id, x.action, x.quantity, x.limit_price, "unsubmitted"))
                self._audit(tenant, "group_staged", {
                    "group_id": group,
                    "client_order_ids": [x.client_order_id for x in intents]
                })
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def confirm_group(self, tenant: str, group: str) -> None:
        """Record confirmation only; caller must authenticate fresh user consent.

        Does not dispatch any order. Broker preview validity must be checked by
        the calling API before this method is invoked.
        """
        with self._lock:
            self._begin()
            try:
                updated = self._db.execute(
                    "UPDATE groups SET confirmed_at=? WHERE tenant_id=?"
                    " AND group_id=? AND confirmed_at IS NULL",
                    (_utc(), tenant, group))
                if updated.rowcount != 1:
                    raise LiveJournalError("unknown or already confirmed group")
                self._audit(tenant, "group_confirmed", {"group_id": group})
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def reserve_submission(self, tenant: str, client_order_id: str) -> None:
        """Persist UNKNOWN before any outbound call. Once reserved, no retry.

        Recovery must reconcile by client order ID with the actual broker.
        """
        with self._lock:
            self._begin()
            try:
                updated = self._db.execute(
                    "UPDATE orders SET state='submission_unknown'"
                    " WHERE tenant_id=? AND client_order_id=? AND state='unsubmitted'"
                    " AND EXISTS (SELECT 1 FROM groups WHERE groups.tenant_id=orders.tenant_id"
                    " AND groups.group_id=orders.group_id AND confirmed_at IS NOT NULL)",
                    (tenant, client_order_id))
                if updated.rowcount != 1:
                    raise LiveJournalError("not confirmed or already submitted")
                self._audit(tenant, "submission_reserved",
                            {"client_order_id": client_order_id})
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def reconcile_order(self, tenant: str, client_order_id: str,
                        state: str, broker_order_id: str | None) -> None:
        """Apply authenticated broker status; never infer rejection from timeout.

        Reconciliation is intentionally forbidden for an unsubmitted order.
        """
        if state not in BROKER_STATES - {"unsubmitted", "submission_unknown"}:
            raise LiveJournalError("invalid reconciled broker state")
        if broker_order_id is not None and (not broker_order_id or len(broker_order_id) > 160):
            raise LiveJournalError("invalid broker order ID")
        with self._lock:
            self._begin()
            try:
                row = self._db.execute(
                    "SELECT state,broker_order_id,cumulative_filled,quantity FROM orders"
                    " WHERE tenant_id=? AND client_order_id=?", (tenant, client_order_id)
                ).fetchone()
                if row is None or row["state"] == "unsubmitted":
                    raise LiveJournalError("unknown or unsubmitted order")
                if row["state"] in FINAL_STATES and row["state"] != state:
                    raise LiveJournalError("cannot override final broker state")
                if row["broker_order_id"] and broker_order_id and row["broker_order_id"] != broker_order_id:
                    raise LiveJournalError("conflicting broker order ID")
                if state == "filled" and row["cumulative_filled"] != row["quantity"]:
                    raise LiveJournalError("filled requires reconciled executions")
                if state == "rejected" and row["cumulative_filled"] != 0:
                    raise LiveJournalError("cannot reject executed order")
                if state == "accepted" and row["cumulative_filled"] > 0:
                    raise LiveJournalError("cannot erase partial fill")
                if state == "partially_filled" and not (0 < row["cumulative_filled"] < row["quantity"]):
                    raise LiveJournalError("partial fill requires reconciled executions")
                if row["state"] == state and (not broker_order_id or row["broker_order_id"] == broker_order_id):
                    self._db.execute("COMMIT")
                    return
                self._db.execute(
                    "UPDATE orders SET state=?,broker_order_id=COALESCE(broker_order_id,?)"
                    " WHERE tenant_id=? AND client_order_id=?",
                    (state, broker_order_id, tenant, client_order_id))
                self._audit(tenant, "broker_reconciled", {
                    "client_order_id": client_order_id, "state": state,
                    "broker_order_id": broker_order_id})
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def record_execution(self, tenant: str, client_order_id: str,
                         execution_id: str, quantity: int, price: str,
                         executed_at: str, broker_order_id: str) -> bool:
        """Idempotently record a verified incremental broker fill.

        Only authenticated broker-originating execution facts may be passed.
        On conflicting identifiers, fail closed rather than rewriting history.
        """
        if not execution_id or len(execution_id) > 160 or not broker_order_id:
            raise LiveJournalError("missing execution identifier")
        if type(quantity) is not int or quantity <= 0:
            raise LiveJournalError("invalid fill quantity")
        try:
            value = Decimal(price)
            datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise LiveJournalError("invalid execution price or timestamp") from exc
        if not value.is_finite() or value <= 0:
            raise LiveJournalError("invalid fill price")
        with self._lock:
            self._begin()
            try:
                row = self._db.execute(
                    "SELECT * FROM orders WHERE tenant_id=? AND client_order_id=?",
                    (tenant, client_order_id)).fetchone()
                if row is None or row["state"] == "unsubmitted":
                    raise LiveJournalError("execution without submitted order")
                if row["broker_order_id"] and row["broker_order_id"] != broker_order_id:
                    raise LiveJournalError("conflicting broker order ID")
                duplicate = self._db.execute(
                    "SELECT * FROM executions WHERE tenant_id=? AND broker_id=?"
                    " AND account_id=? AND execution_id=?",
                    (tenant, row["broker_id"], row["account_id"], execution_id)
                ).fetchone()
                if duplicate:
                    same = (duplicate["client_order_id"] == client_order_id and
                            duplicate["quantity"] == quantity and
                            Decimal(duplicate["price"]) == value and
                            duplicate["executed_at"] == executed_at)
                    if not same:
                        raise LiveJournalError("conflicting duplicate execution ID")
                    self._db.execute("COMMIT")
                    return False
                filled = row["cumulative_filled"] + quantity
                if filled > row["quantity"]:
                    raise LiveJournalError("fill exceeds requested quantity")
                if row["state"] in {"rejected", "canceled"}:
                    # Late fills can be valid after cancellation, but require an
                    # explicit reconciliation policy rather than silent mutation.
                    raise LiveJournalError("terminal order requires manual reconciliation")
                self._db.execute(
                    "INSERT INTO executions VALUES(?,?,?,?,?,?,?,?)",
                    (tenant, row["broker_id"], row["account_id"], execution_id,
                     client_order_id, quantity, price, executed_at))
                new_state = "filled" if filled == row["quantity"] else "partially_filled"
                self._db.execute(
                    "UPDATE orders SET cumulative_filled=?,state=?,"
                    " broker_order_id=COALESCE(broker_order_id,?)"
                    " WHERE tenant_id=? AND client_order_id=?",
                    (filled, new_state, broker_order_id, tenant, client_order_id))
                self._audit(tenant, "execution_recorded", {
                    "client_order_id": client_order_id, "execution_id": execution_id,
                    "quantity": quantity, "price": price, "state": new_state})
                self._db.execute("COMMIT")
                return True
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def orders_for_group(self, tenant: str, group: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM orders WHERE tenant_id=? AND group_id=?"
                " ORDER BY broker_id, account_id", (tenant, group)
            ).fetchall()
            return [dict(row) for row in rows]

    def verify_audit_chain(self) -> bool:
        """Tamper-evident audit hashes, not tamper-proof external anchoring."""
        with self._lock:
            prior = "GENESIS"
            for row in self._db.execute("SELECT * FROM audit ORDER BY seq"):
                if row["previous_hash"] != prior:
                    return False
                computed = sha256(json.dumps(
                    [row["at"], row["tenant_id"], row["event"],
                     row["details"], prior],
                    separators=(",", ":")
                ).encode("utf-8")).hexdigest()
                if computed != row["entry_hash"]:
                    return False
                prior = computed
            return True
