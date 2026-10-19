"""Durable live-order intent, broker reconciliation and audit ledger.

This module NEVER connects to a broker or submits orders. Callers must enforce
authenticated customer authorization, broker-side idempotency, and live broker
order permission checks before adding any execution gateway.

A broker timeout is UNKNOWN, not REJECTED. Never blindly retry submission.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hmac
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import time
from threading import RLock
from typing import Any, Callable, Iterable
from uuid import UUID
from datetime import datetime, timezone


ALLOWED_ACTIONS = frozenset({"buyToOpen", "sellToClose", "sellToOpen", "buyToClose"})
BROKER_STATES = frozenset({
    "unsubmitted", "submission_unknown", "accepted", "partially_filled",
    "filled", "canceled", "rejected",
})
FINAL_STATES = frozenset({"filled", "canceled", "rejected"})

# Schema v2: execution identity includes the broker order ID, orders carry a
# reconciliation flag, and a confirmation has an expiry. Pre-release databases
# from schema v1 are migrated transactionally without discarding audit history.
SCHEMA_VERSION = 2
MAX_CONTRACTS_PER_ORDER = 1000      # per-order ceiling; make this per-tenant policy later
MAX_LIMIT_PRICE = Decimal("100000")
CONFIRMATION_TTL_SECONDS = 120
MAX_CONFIRMATION_TTL_SECONDS = 600
_PRICE_RE = re.compile(r"\d{1,6}(\.\d{1,4})?")


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

    def validate(self, max_contracts: int = MAX_CONTRACTS_PER_ORDER) -> None:
        for value in (self.tenant_id, self.group_id, self.broker_id,
                      self.account_id, self.contract_id, self.client_order_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 160:
                raise LiveJournalError("missing or oversized identifier")
        for value in (self.group_id, self.client_order_id):
            _require_canonical_uuid(value)
        if self.action not in ALLOWED_ACTIONS:
            raise LiveJournalError("unknown order action")
        if type(self.quantity) is not int or not 1 <= self.quantity <= max_contracts:
            raise LiveJournalError("invalid contracts")
        # A plain decimal string only: no whitespace, exponent, sign, NaN or Infinity.
        if not isinstance(self.limit_price, str) or not _PRICE_RE.fullmatch(self.limit_price):
            raise LiveJournalError("limit price must be a plain decimal string")
        price = Decimal(self.limit_price)
        if price <= 0 or price > MAX_LIMIT_PRICE:
            raise LiveJournalError("limit price out of range")


def _require_canonical_uuid(value: str) -> None:
    """Reject alternate spellings (case, braces, urn:, no hyphens) of one UUID."""
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise LiveJournalError("group and client order IDs must be UUIDs") from exc
    if canonical != value:
        raise LiveJournalError("UUIDs must be lowercase hyphenated canonical form")


def order_set_digest(orders: Iterable[Any]) -> str:
    """Canonical digest of every parameter of a set of orders.

    The caller computes it over what the customer actually reviewed (and the
    broker previewed); ``confirm_group`` refuses a confirmation whose digest
    does not match the staged orders.
    """
    def field(order: Any, name: str) -> Any:
        return order[name] if isinstance(order, (dict, sqlite3.Row)) else getattr(order, name)

    names = ("client_order_id", "broker_id", "account_id", "contract_id",
             "action", "quantity", "limit_price")
    rows = sorted([field(o, n) for n in names] for o in orders)
    return sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def _normalize_timestamp(value: str) -> str:
    """Timezone-aware ISO timestamp normalized to UTC; naive times are rejected."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError) as exc:
        raise LiveJournalError("invalid execution price or timestamp") from exc
    if parsed.tzinfo is None:
        raise LiveJournalError("execution timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class LiveOrderJournal:
    """Transactional SQLite record for one deployment; NOT a public API.

    Each method takes a tenant scope and never returns data from another tenant.
    Multi-instance deployments need a centralized transactional database rather
    than SQLite on independent application hosts.
    """

    def __init__(self, db_path: str | Path, clock: Callable[[], float] = time.time):
        self._lock = RLock()
        self._clock = clock
        self._db = sqlite3.connect(str(db_path), isolation_level=None,
                                   check_same_thread=False, timeout=20)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=20000")
        existing = self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='orders'").fetchone()
        if existing:
            try:
                self._upgrade_schema()
            except Exception:
                self._db.close()
                raise
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS groups (
                tenant_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                confirmed_at TEXT,
                confirm_expires_at REAL,
                confirmed_digest TEXT,
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
                needs_reconciliation INTEGER NOT NULL DEFAULT 0,
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
                broker_order_id TEXT NOT NULL,
                execution_id TEXT NOT NULL,
                client_order_id TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                price TEXT NOT NULL,
                executed_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, broker_id, account_id, broker_order_id, execution_id),
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
            CREATE INDEX IF NOT EXISTS executions_by_order
                ON executions(tenant_id, client_order_id);
        """)
        self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _upgrade_schema(self) -> None:
        """Upgrade under a write lock; failures leave the legacy database intact.

        Legacy confirmations have no expiry/binding, so require fresh confirmation
        for unsubmitted groups. Reserved orders retain their state and cannot renew.
        """
        self._begin()
        try:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version == SCHEMA_VERSION:
                self._db.execute("COMMIT")
                return
            if version not in (0, 1):
                raise LiveJournalError(f"unsupported journal schema v{version}")
            required = {
                'groups': {'tenant_id', 'group_id', 'created_at', 'confirmed_at'},
                'orders': {'tenant_id', 'group_id', 'client_order_id', 'broker_id', 'account_id',
                           'contract_id', 'action', 'quantity', 'limit_price', 'state',
                           'broker_order_id', 'cumulative_filled'},
                'executions': {'tenant_id', 'broker_id', 'account_id', 'execution_id',
                               'client_order_id', 'quantity', 'price', 'executed_at'},
                'audit': {'seq', 'at', 'tenant_id', 'event', 'details', 'previous_hash', 'entry_hash'},
            }
            for table, columns in required.items():
                actual = {r['name'] for r in self._db.execute(f'PRAGMA table_info({table})')}
                if actual != columns:
                    raise LiveJournalError('unrecognized legacy journal schema; database unchanged')
            if not self.verify_audit_chain():
                raise LiveJournalError('legacy audit verification failed; database unchanged')
            self._db.execute('ALTER TABLE groups ADD COLUMN confirm_expires_at REAL')
            self._db.execute('ALTER TABLE groups ADD COLUMN confirmed_digest TEXT')
            self._db.execute('ALTER TABLE orders ADD COLUMN needs_reconciliation INTEGER NOT NULL DEFAULT 0')
            self._db.execute('ALTER TABLE executions RENAME TO executions_legacy')
            self._db.execute('''CREATE TABLE executions (
                tenant_id TEXT NOT NULL, broker_id TEXT NOT NULL, account_id TEXT NOT NULL,
                broker_order_id TEXT NOT NULL, execution_id TEXT NOT NULL,
                client_order_id TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0),
                price TEXT NOT NULL, executed_at TEXT NOT NULL,
                PRIMARY KEY(tenant_id,broker_id,account_id,broker_order_id,execution_id),
                FOREIGN KEY(tenant_id,client_order_id) REFERENCES orders(tenant_id,client_order_id))''')
            rows = self._db.execute('''SELECT e.*, o.broker_order_id FROM executions_legacy e
                LEFT JOIN orders o ON o.tenant_id=e.tenant_id AND o.client_order_id=e.client_order_id
                AND o.broker_id=e.broker_id AND o.account_id=e.account_id''').fetchall()
            for row in rows:
                if not row['broker_order_id']:
                    raise LiveJournalError('legacy fill has no matching broker order; database unchanged')
                # Preserve original timestamp bytes. Duplicate comparison normalizes
                # both sides; malformed legacy values are retained for operator review.
                self._db.execute('INSERT INTO executions VALUES(?,?,?,?,?,?,?,?,?)',
                    tuple(row[k] for k in ('tenant_id', 'broker_id', 'account_id',
                          'broker_order_id', 'execution_id', 'client_order_id', 'quantity',
                          'price', 'executed_at')))
                try:
                    _normalize_timestamp(row['executed_at'])
                except LiveJournalError:
                    self._db.execute('UPDATE orders SET needs_reconciliation=1 WHERE tenant_id=? AND client_order_id=?',
                                     (row['tenant_id'], row['client_order_id']))
            self._db.execute('DROP TABLE executions_legacy')
            self._db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            self._db.execute('COMMIT')
        except Exception:
            self._db.execute('ROLLBACK')
            raise

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

    def group_digest(self, tenant: str, group: str) -> str:
        """Digest of the staged orders, for comparison with what was reviewed."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM orders WHERE tenant_id=? AND group_id=?", (tenant, group)
            ).fetchall()
        if not rows:
            raise LiveJournalError("unknown group")
        return order_set_digest(rows)

    def confirm_group(self, tenant: str, group: str, *, expected_digest: str,
                      ttl_seconds: int = CONFIRMATION_TTL_SECONDS) -> None:
        """Record a confirmation bound to the exact orders that were reviewed.

        ``expected_digest`` is ``order_set_digest`` over the order set the
        customer saw (and the broker previewed). The confirmation expires after
        ``ttl_seconds``; ``reserve_submission`` refuses an expired one. The
        caller must still authenticate fresh user consent.
        """
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_CONFIRMATION_TTL_SECONDS:
            raise LiveJournalError("invalid confirmation lifetime")
        with self._lock:
            self._begin()
            try:
                rows = self._db.execute(
                    "SELECT * FROM orders WHERE tenant_id=? AND group_id=?", (tenant, group)
                ).fetchall()
                if not rows or any(row['state'] != 'unsubmitted' for row in rows):
                    raise LiveJournalError("unknown or already confirmed group")
                actual = order_set_digest(rows)
                if not isinstance(expected_digest, str) or not hmac.compare_digest(
                        expected_digest.encode(), actual.encode()):
                    raise LiveJournalError("confirmation does not match the staged orders")
                expires = self._clock() + ttl_seconds
                updated = self._db.execute(
                    "UPDATE groups SET confirmed_at=?, confirm_expires_at=?, confirmed_digest=?"
                    " WHERE tenant_id=? AND group_id=? AND (confirmed_at IS NULL"
                    " OR confirm_expires_at IS NULL OR confirm_expires_at <= ?)",
                    (_utc(), expires, actual, tenant, group, self._clock()))
                if updated.rowcount != 1:
                    raise LiveJournalError("unknown or already confirmed group")
                self._audit(tenant, "group_confirmed", {
                    "group_id": group, "digest": actual, "expires_epoch": expires})
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
                    " AND groups.group_id=orders.group_id AND confirmed_at IS NOT NULL"
                    " AND confirm_expires_at > ?)",
                    (tenant, client_order_id, self._clock()))
                if updated.rowcount != 1:
                    raise LiveJournalError("not confirmed, confirmation expired, or already submitted")
                self._audit(tenant, "submission_reserved",
                            {"client_order_id": client_order_id})
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def reserve_group(self, tenant: str, group: str) -> list[str]:
        """Atomically reserve EVERY order in a confirmed, unexpired group.

        All-or-nothing: if any order is not ``unsubmitted`` or the confirmation
        has lapsed, nothing is reserved and nothing may be sent. Returns the
        client order IDs now persisted as ``submission_unknown``; only then may
        the caller start network I/O.
        """
        with self._lock:
            self._begin()
            try:
                group_row = self._db.execute(
                    "SELECT confirmed_at, confirm_expires_at FROM groups"
                    " WHERE tenant_id=? AND group_id=?", (tenant, group)).fetchone()
                if (group_row is None or group_row["confirmed_at"] is None
                        or group_row["confirm_expires_at"] is None
                        or group_row["confirm_expires_at"] <= self._clock()):
                    raise LiveJournalError("not confirmed, confirmation expired, or unknown group")
                rows = self._db.execute(
                    "SELECT client_order_id, state FROM orders WHERE tenant_id=? AND group_id=?"
                    " ORDER BY client_order_id", (tenant, group)).fetchall()
                if not rows or any(r["state"] != "unsubmitted" for r in rows):
                    raise LiveJournalError("group already submitted or empty")
                self._db.execute(
                    "UPDATE orders SET state='submission_unknown'"
                    " WHERE tenant_id=? AND group_id=? AND state='unsubmitted'", (tenant, group))
                ids = [r["client_order_id"] for r in rows]
                self._audit(tenant, "group_submission_reserved",
                            {"group_id": group, "client_order_ids": ids})
                self._db.execute("COMMIT")
                return ids
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
                         executed_at: str, broker_order_id: str, *,
                         broker_id: str, account_id: str) -> bool:
        """Idempotently record a verified incremental broker fill.

        ``broker_id`` and ``account_id`` come from the authenticated event and
        must match the order. A fill is always recorded once the broker says it
        happened, even after a cancel or reject; contradictory sequences and
        fills outside the limit set ``needs_reconciliation`` instead of being
        dropped. Conflicting duplicates still fail closed.
        """
        if not execution_id or len(execution_id) > 160 or not broker_order_id:
            raise LiveJournalError("missing execution identifier")
        if type(quantity) is not int or quantity <= 0:
            raise LiveJournalError("invalid fill quantity")
        try:
            value = Decimal(price)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise LiveJournalError("invalid execution price or timestamp") from exc
        if not value.is_finite() or value <= 0:
            raise LiveJournalError("invalid fill price")
        when = _normalize_timestamp(executed_at)
        price_text = str(value)
        with self._lock:
            self._begin()
            try:
                row = self._db.execute(
                    "SELECT * FROM orders WHERE tenant_id=? AND client_order_id=?",
                    (tenant, client_order_id)).fetchone()
                if row is None or row["state"] == "unsubmitted":
                    raise LiveJournalError("execution without submitted order")
                if (row["broker_id"], row["account_id"]) != (broker_id, account_id):
                    raise LiveJournalError("execution does not belong to this broker account")
                if row["broker_order_id"] and row["broker_order_id"] != broker_order_id:
                    raise LiveJournalError("conflicting broker order ID")
                duplicate = self._db.execute(
                    "SELECT * FROM executions WHERE tenant_id=? AND broker_id=?"
                    " AND account_id=? AND broker_order_id=? AND execution_id=?",
                    (tenant, broker_id, account_id, broker_order_id, execution_id)
                ).fetchone()
                if duplicate:
                    same = (duplicate["client_order_id"] == client_order_id and
                            duplicate["quantity"] == quantity and
                            Decimal(duplicate["price"]) == value and
                            _normalize_timestamp(duplicate["executed_at"]) == when)
                    if not same:
                        raise LiveJournalError("conflicting duplicate execution ID")
                    self._db.execute("COMMIT")
                    return False
                filled = row["cumulative_filled"] + quantity
                if filled > row["quantity"]:
                    raise LiveJournalError("fill exceeds requested quantity")
                reasons = []
                late = row["state"] in {"rejected", "canceled"}
                if late:
                    reasons.append(f"fill_after_{row['state']}")
                limit = Decimal(row["limit_price"])
                if (row["action"].startswith("buy") and value > limit) or \
                        (row["action"].startswith("sell") and value < limit):
                    reasons.append("outside_limit")
                if filled == row["quantity"]:
                    new_state = "filled"
                else:
                    new_state = row["state"] if late else "partially_filled"
                self._db.execute(
                    "INSERT INTO executions(tenant_id,broker_id,account_id,broker_order_id,"
                    "execution_id,client_order_id,quantity,price,executed_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (tenant, broker_id, account_id, broker_order_id, execution_id,
                     client_order_id, quantity, price_text, when))
                self._db.execute(
                    "UPDATE orders SET cumulative_filled=?,state=?,"
                    " broker_order_id=COALESCE(broker_order_id,?),"
                    " needs_reconciliation=MAX(needs_reconciliation,?)"
                    " WHERE tenant_id=? AND client_order_id=?",
                    (filled, new_state, broker_order_id, 1 if reasons else 0,
                     tenant, client_order_id))
                self._audit(tenant, "execution_recorded", {
                    "client_order_id": client_order_id, "execution_id": execution_id,
                    "quantity": quantity, "price": price_text, "state": new_state,
                    "reconcile": reasons})
                self._db.execute("COMMIT")
                return True
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def orders_needing_reconciliation(self, tenant: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM orders WHERE tenant_id=? AND needs_reconciliation=1"
                " ORDER BY group_id, broker_id, account_id", (tenant,)).fetchall()
            return [dict(row) for row in rows]

    def clear_reconciliation(self, tenant: str, client_order_id: str, note: str) -> None:
        """Operator action after comparing the order with the broker's own records."""
        if not note or len(note) > 500:
            raise LiveJournalError("a reconciliation note is required")
        with self._lock:
            self._begin()
            try:
                updated = self._db.execute(
                    "UPDATE orders SET needs_reconciliation=0 WHERE tenant_id=?"
                    " AND client_order_id=? AND needs_reconciliation=1",
                    (tenant, client_order_id))
                if updated.rowcount != 1:
                    raise LiveJournalError("order is not flagged for reconciliation")
                self._audit(tenant, "reconciliation_cleared",
                            {"client_order_id": client_order_id, "note": note})
                self._db.execute("COMMIT")
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
