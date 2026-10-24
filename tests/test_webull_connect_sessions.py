from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from crier.webull_connect_sessions import ConnectSessions, SessionRejected


CALLBACK = "https://connect.example.com/webull/callback"


def store(tmp_path):
    return ConnectSessions(tmp_path / "connect.sqlite3", callback=CALLBACK)


def consume(db, session, **overrides):
    args = dict(state=session.state, browser_binding=session.browser_binding,
                customer="customer-a", environment="sandbox", callback=CALLBACK, now=101)
    args.update(overrides)
    return db.consume(**args)


def test_restart_single_use_and_no_raw_secrets(tmp_path):
    db = store(tmp_path)
    session = db.create(customer="customer-a", environment="sandbox", now=100)
    assert len(session.state) >= 43 and session.state != session.browser_binding
    assert session.state not in repr(session)
    assert session.browser_binding not in repr(session)
    with sqlite3.connect(tmp_path / "connect.sqlite3") as con:
        stored = str(con.execute("SELECT * FROM connect_sessions").fetchall())
    assert session.state not in stored and session.browser_binding not in stored
    assert consume(store(tmp_path), session) == "customer-a"
    with pytest.raises(SessionRejected):
        consume(db, session)


@pytest.mark.parametrize("bad", [
    {"state": "wrong"}, {"browser_binding": "wrong"}, {"customer": "customer-b"},
    {"environment": "production"}, {"callback": CALLBACK + "?other=1"},
])
def test_invalid_attempt_does_not_burn_session(tmp_path, bad):
    db = store(tmp_path)
    session = db.create(customer="customer-a", environment="sandbox", now=100)
    with pytest.raises(SessionRejected, match="Authorization session rejected"):
        consume(db, session, **bad)
    assert consume(db, session) == "customer-a"


@pytest.mark.parametrize("now", [99, 400, 401])
def test_time_boundaries(tmp_path, now):
    db = store(tmp_path)
    session = db.create(customer="customer-a", environment="sandbox", now=100)
    with pytest.raises(SessionRejected):
        consume(db, session, now=now)


def test_parallel_callbacks_accept_exactly_once(tmp_path):
    db = store(tmp_path)
    session = db.create(customer="customer-a", environment="sandbox", now=100)

    def attempt(_):
        try:
            return consume(store(tmp_path), session)
        except SessionRejected:
            return "rejected"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count("customer-a") == 1
    assert results.count("rejected") == 7


@pytest.mark.parametrize("callback", ["http://example.com/cb", "https://user:pass@example.com/cb",
                                      "https://example.com/cb#fragment", "https://example.com/cb?q=1"])
def test_unsafe_callback_configuration_rejected(tmp_path, callback):
    with pytest.raises(ValueError):
        ConnectSessions(tmp_path / "connect.sqlite3", callback=callback)


@pytest.mark.parametrize("field,value", [("customer", ""), ("customer", "x" * 201),
                                         ("environment", "paper"), ("now", float("nan"))])
def test_invalid_create_rejected(tmp_path, field, value):
    args = dict(customer="customer-a", environment="sandbox", now=100)
    args[field] = value
    with pytest.raises(ValueError):
        store(tmp_path).create(**args)


def test_expired_rows_pruned_during_creation(tmp_path):
    db = store(tmp_path)
    db.create(customer="customer-a", environment="sandbox", now=100)
    db.create(customer="customer-b", environment="sandbox", now=400)
    with sqlite3.connect(tmp_path / "connect.sqlite3") as con:
        assert con.execute("SELECT COUNT(*) FROM connect_sessions").fetchone()[0] == 1


@pytest.mark.parametrize("state", [None, [], "x" * 129, "\ud800"])
def test_malformed_callback_state_rejected_without_leak(tmp_path, state):
    db = store(tmp_path)
    session = db.create(customer="customer-a", environment="sandbox", now=100)
    with pytest.raises(SessionRejected) as caught:
        consume(db, session, state=state)
    assert str(caught.value) == "Authorization session rejected"
    assert consume(db, session) == "customer-a"
