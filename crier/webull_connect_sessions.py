"""Server-side Connect OAuth state groundwork; no Webull requests or token storage.

Not wired to a public endpoint. A future authenticated gateway must put the
browser binding in a Secure, HttpOnly cookie and enforce its own creation limits.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit


class SessionRejected(ValueError):
    """Uniform failure that discloses no state, identity or credentials."""


@dataclass(frozen=True)
class PendingSession:
    state: str = field(repr=False)
    browser_binding: str = field(repr=False)
    expires_at: float


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit and not any(
        ord(c) < 33 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)


def _timestamp(now):
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
        raise ValueError("Invalid session time")
    return now


class ConnectSessions:
    # Login-session lifetime, not the broker authorization-code/token lifetime.
    lifetime = 300

    def __init__(self, path, *, callback):
        if not _text(callback, 2048):
            raise ValueError("Expected a registered HTTPS callback without query or fragment")
        parsed = urlsplit(callback)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or "?" in callback or "#" in callback or "\\" in callback):
            raise ValueError("Expected a registered HTTPS callback without query or fragment")
        # Accessing port also rejects malformed or out-of-range ports.
        parsed.port
        self.callback = callback
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS connect_sessions (
                state_hash TEXT PRIMARY KEY, binding_hash TEXT NOT NULL,
                customer TEXT NOT NULL, environment TEXT NOT NULL, callback TEXT NOT NULL,
                created_at REAL NOT NULL, expires_at REAL NOT NULL)""")
            con.execute("CREATE INDEX IF NOT EXISTS connect_session_expiry ON connect_sessions(expires_at)")

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, timeout=15)
        try:
            with con:
                yield con
        finally:
            con.close()

    def create(self, *, customer, environment, now=None):
        if not _text(customer, 200) or environment not in ("sandbox", "production"):
            raise ValueError("Invalid authorization scope")
        now = _timestamp(now)
        session = PendingSession(secrets.token_urlsafe(32), secrets.token_urlsafe(32),
                                 now + self.lifetime)
        with self._connect() as con:
            con.execute("DELETE FROM connect_sessions WHERE expires_at <= ?", (now,))
            con.execute("INSERT INTO connect_sessions VALUES (?,?,?,?,?,?,?)", (
                _digest(session.state), _digest(session.browser_binding), customer,
                environment, self.callback, now, session.expires_at))
        return session

    def consume(self, *, state, browser_binding, customer, environment, callback, now=None):
        """Atomically accept once, before any authorization-code exchange.

        ``customer`` must come from the authenticated gateway/browser session.
        A failed or uncertain token exchange requires a new authorization flow;
        it must not cause a consumed state/code to be replayed.
        """
        try:
            now = _timestamp(now)
        except ValueError:
            raise SessionRejected("Authorization session rejected") from None
        if (not _text(state, 128) or not _text(browser_binding, 128)
                or not _text(customer, 200) or environment not in ("sandbox", "production")
                or callback != self.callback):
            raise SessionRejected("Authorization session rejected")
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            result = con.execute("""DELETE FROM connect_sessions
                WHERE state_hash=? AND binding_hash=? AND customer=? AND environment=?
                AND callback=? AND created_at<=? AND expires_at>?""", (
                    _digest(state), _digest(browser_binding), customer, environment,
                    callback, now, now))
            if result.rowcount != 1:
                raise SessionRejected("Authorization session rejected")
        return customer
