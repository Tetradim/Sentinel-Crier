"""Durable, device-bound OAuth custody, independent of provider HTTP transport.

The caller authenticates native and browser owners independently and validates
provider grants. Launch and callback browser owners must match the flow owner. Supply an external
32-byte encryption key; this module never creates or persists a key. An exchange
claim is irreversible: interrupted exchanges remain uncertain until cancellation
or expiry, and must never trigger an automatic provider exchange retry.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class FlowRejected(ValueError):
    """Uniform public error, deliberately excluding credentials and identifiers."""

    def __init__(self):
        super().__init__("Authorization flow rejected")


_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_CHALLENGE = re.compile(r"[a-f0-9]{64}\Z")
_ACTIVE = ("pending", "launched", "exchanging", "ready")


def _token(value):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise FlowRejected()
    return value


def _owner(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise FlowRejected()
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise FlowRejected() from None
    if value.strip() != value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise FlowRejected()
    return value


def _hash(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _now(value):
    value = time.time() if value is None else value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise FlowRejected()
    return float(value)


class FlowStore:
    """SQLite transactions serialize one-use transitions across processes."""

    def __init__(self, db_path, encryption_key, *, session_ttl=300, ready_ttl=60,
                 max_active_per_owner=8, max_active_per_challenge=4):
        if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
            raise ValueError("An external 32-byte OAuth encryption key is required")
        for value, maximum in ((session_ttl, 300), (ready_ttl, 60),
                               (max_active_per_owner, 100), (max_active_per_challenge, 100)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid OAuth custody configuration")
        self._path = str(db_path)
        self._cipher = AESGCM(encryption_key)
        self._session_ttl = session_ttl
        self._ready_ttl = ready_ttl
        self._owner_quota = max_active_per_owner
        self._challenge_quota = max_active_per_challenge
        with self._transaction() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS oauth_flows (
                flow TEXT PRIMARY KEY, owner TEXT NOT NULL, provider TEXT NOT NULL,
                purpose TEXT NOT NULL, environment TEXT NOT NULL, challenge TEXT NOT NULL,
                created_at REAL NOT NULL, expires_at REAL NOT NULL, last_at REAL NOT NULL,
                stage TEXT NOT NULL, ticket_hash TEXT UNIQUE, state_hash TEXT UNIQUE,
                binding_hash TEXT, state_ciphertext BLOB, grant_ciphertext BLOB,
                ready_until REAL
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS oauth_owner ON oauth_flows(owner, challenge, stage, expires_at)")
            con.execute("CREATE INDEX IF NOT EXISTS oauth_expiry ON oauth_flows(expires_at)")

    @contextmanager
    def _transaction(self):
        con = sqlite3.connect(self._path, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA secure_delete=ON")
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except FlowRejected:
            # Expiry scrubbing must persist even when the triggering request fails.
            con.commit()
            raise
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _aad(row, kind):
        return json.dumps(["sentinel-crier-oauth-v1", kind, row["flow"], row["owner"],
                           row["challenge"], row["provider"], row["environment"],
                           row["purpose"]], separators=(",", ":")).encode("utf-8")

    def _encrypt(self, row, kind, plaintext):
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, plaintext, self._aad(row, kind))

    def _decrypt(self, row, kind, ciphertext):
        try:
            return self._cipher.decrypt(ciphertext[:12], ciphertext[12:], self._aad(row, kind))
        except (InvalidTag, TypeError, ValueError):
            raise FlowRejected() from None

    @staticmethod
    def _metadata(row):
        return {key: row[key] for key in ("flow", "provider", "purpose", "environment", "stage", "expires_at", "ready_until")}

    @staticmethod
    def _clear(con, flow, stage, now):
        con.execute("""UPDATE oauth_flows SET stage=?, last_at=?, ticket_hash=NULL,
            state_hash=NULL, binding_hash=NULL, state_ciphertext=NULL,
            grant_ciphertext=NULL, ready_until=NULL WHERE flow=?""", (stage, now, flow))

    def _live(self, con, row, now):
        if row is None or now < row["last_at"]:
            raise FlowRejected()
        if now >= row["expires_at"] or (row["stage"] == "ready" and now >= row["ready_until"]):
            self._clear(con, row["flow"], "expired", now)
            raise FlowRejected()
        return row

    @staticmethod
    def _find(con, flow):
        return con.execute("SELECT * FROM oauth_flows WHERE flow=?", (flow,)).fetchone()

    def create(self, owner, provider, purpose, environment, challenge, now=None):
        _owner(owner)
        if provider not in ("alpaca", "discord") or purpose not in ("alerts", "trade") or environment not in ("paper", "live"):
            raise FlowRejected()
        if provider == "discord" and purpose != "alerts":
            raise FlowRejected()
        if not isinstance(challenge, str) or not _CHALLENGE.fullmatch(challenge):
            raise FlowRejected()
        with self._transaction() as con:
            current = _now(now)  # Read real time only after acquiring the write lock.
            self._cleanup(con, current, 100)
            counts = con.execute("""SELECT COUNT(*), COALESCE(SUM(challenge=?),0)
                FROM oauth_flows WHERE owner=? AND stage IN ('pending','launched','exchanging','ready')
                AND expires_at>? AND (ready_until IS NULL OR ready_until>?)""",
                (challenge, owner, current, current)).fetchone()
            if counts[0] >= self._owner_quota or counts[1] >= self._challenge_quota:
                raise FlowRejected()
            flow, ticket, state = (secrets.token_urlsafe(32) for _ in range(3))
            row = dict(flow=flow, owner=owner, provider=provider, purpose=purpose,
                       environment=environment, challenge=challenge)
            encrypted_state = self._encrypt(row, "state", state.encode("ascii"))
            deadline = current + self._session_ttl
            con.execute("""INSERT INTO oauth_flows
                (flow,owner,provider,purpose,environment,challenge,created_at,expires_at,last_at,
                 stage,ticket_hash,state_hash,state_ciphertext)
                VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?,?)""",
                (flow, owner, provider, purpose, environment, challenge, current, deadline,
                 current, _hash(ticket), _hash(state), encrypted_state))
            return dict(flow=flow, launch_ticket=ticket, expires_at=deadline)

    def launch(self, ticket, now=None, *, owner):
        _owner(owner)
        _token(ticket)
        with self._transaction() as con:
            current = _now(now)
            row = con.execute("SELECT * FROM oauth_flows WHERE ticket_hash=?", (_hash(ticket),)).fetchone()
            if row is None or row["owner"] != owner:
                raise FlowRejected()
            self._live(con, row, current)
            if row["stage"] != "pending":
                raise FlowRejected()
            state = self._decrypt(row, "state", row["state_ciphertext"]).decode("ascii")
            binding = secrets.token_urlsafe(32)
            con.execute("""UPDATE oauth_flows SET stage='launched', last_at=?, ticket_hash=NULL,
                state_ciphertext=NULL, binding_hash=? WHERE flow=?""", (current, _hash(binding), row["flow"]))
            result = self._metadata(row)
            result.update(stage="launched", state=state, browser_binding=binding)
            return result

    def claim_callback(self, provider, state, browser_binding, now=None, *, owner):
        _owner(owner)
        _token(state)
        _token(browser_binding)
        if provider not in ("alpaca", "discord"):
            raise FlowRejected()
        with self._transaction() as con:
            current = _now(now)
            row = con.execute("SELECT * FROM oauth_flows WHERE state_hash=?", (_hash(state),)).fetchone()
            if row is None or row["owner"] != owner or row["provider"] != provider or row["stage"] != "launched" or not hmac.compare_digest(row["binding_hash"], _hash(browser_binding)):
                raise FlowRejected()
            self._live(con, row, current)
            con.execute("""UPDATE oauth_flows SET stage='exchanging', last_at=?,
                state_hash=NULL, binding_hash=NULL WHERE flow=?""", (current, row["flow"]))
            result = self._metadata(row)
            result["stage"] = "exchanging"
            return result

    def complete(self, flow, grant, now=None):
        _token(flow)
        try:
            if not isinstance(grant, dict) or not grant or not all(isinstance(key, str) for key in grant):
                raise ValueError()
            payload = json.dumps(grant, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if len(payload) > 65536:
                raise ValueError()
        except (TypeError, ValueError, RecursionError):
            raise FlowRejected() from None
        with self._transaction() as con:
            current = _now(now)
            row = self._live(con, self._find(con, flow), current)
            if row["stage"] != "exchanging":
                raise FlowRejected()
            encrypted = self._encrypt(row, "grant", payload)
            con.execute("""UPDATE oauth_flows SET stage='ready', last_at=?,
                grant_ciphertext=?, ready_until=? WHERE flow=?""",
                (current, encrypted, min(current + self._ready_ttl, row["expires_at"]), flow))

    def fail(self, flow, now=None):
        _token(flow)
        with self._transaction() as con:
            current = _now(now)
            row = self._live(con, self._find(con, flow), current)
            if row["stage"] != "exchanging":
                raise FlowRejected()
            self._clear(con, flow, "failed", current)

    def status(self, owner, flow, now=None):
        _owner(owner)
        _token(flow)
        with self._transaction() as con:
            current = _now(now)
            row = self._find(con, flow)
            if row is None or row["owner"] != owner or current < row["last_at"]:
                raise FlowRejected()
            if row["stage"] in _ACTIVE:
                try:
                    self._live(con, row, current)
                except FlowRejected:
                    row = self._find(con, flow)
            return self._metadata(row)

    def _device_row(self, con, owner, flow, proof, current):
        row = self._find(con, flow)
        if row is None or row["owner"] != owner or not hmac.compare_digest(row["challenge"], _hash(proof)):
            raise FlowRejected()
        return self._live(con, row, current)

    def redeem(self, owner, flow, proof, now=None):
        _owner(owner)
        _token(flow)
        _token(proof)
        with self._transaction() as con:
            current = _now(now)
            row = self._device_row(con, owner, flow, proof, current)
            if row["stage"] != "ready":
                raise FlowRejected()
            plaintext = self._decrypt(row, "grant", row["grant_ciphertext"])
            try:
                grant = json.loads(plaintext)
            except (ValueError, UnicodeError):
                raise FlowRejected() from None
            self._clear(con, flow, "redeemed", current)
            return grant

    def cancel(self, owner, flow, proof, now=None):
        _owner(owner)
        _token(flow)
        _token(proof)
        with self._transaction() as con:
            current = _now(now)
            row = self._device_row(con, owner, flow, proof, current)
            if row["stage"] not in _ACTIVE:
                raise FlowRejected()
            self._clear(con, flow, "cancelled", current)

    @staticmethod
    def _cleanup(con, current, limit):
        cursor = con.execute("""DELETE FROM oauth_flows WHERE flow IN (
            SELECT flow FROM oauth_flows WHERE expires_at<=? OR
            (stage='ready' AND ready_until<=?) ORDER BY expires_at LIMIT ?)
            """, (current, current, limit))
        return cursor.rowcount

    def cleanup(self, now=None, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise FlowRejected()
        with self._transaction() as con:
            return self._cleanup(con, _now(now), limit)
