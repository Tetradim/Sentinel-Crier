"""Offline custody invariants; run in the isolated OAuth dependency environment."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import secrets
import sqlite3
import threading
import time

import pytest

pytest.importorskip("cryptography", minversion="50")
from crier.oauth_flows import FlowRejected, FlowStore

KEY = b"k" * 32
PROOF = secrets.token_urlsafe(32)
CHALLENGE = hashlib.sha256(PROOF.encode()).hexdigest()
GRANT = {"access_token": "synthetic-credential-do-not-persist", "scope": "account:read"}


def store(tmp_path, **kwargs):
    return FlowStore(tmp_path / "oauth.sqlite3", KEY, **kwargs)


def begin(db, **kwargs):
    args = dict(owner="owner-a", provider="alpaca", purpose="alerts", environment="paper", challenge=CHALLENGE, now=100)
    args.update(kwargs)
    return db.create(**args)


def claimed(db, **kwargs):
    flow = begin(db, **kwargs)
    launch = db.launch(flow["launch_ticket"], now=101, owner="owner-a")
    db.claim_callback("alpaca", launch["state"], launch["browser_binding"], now=102, owner="owner-a")
    return flow, launch


def ready(db, **kwargs):
    flow, launch = claimed(db, **kwargs)
    db.complete(flow["flow"], GRANT, now=103)
    return flow, launch


def test_restart_encrypted_secrets_and_one_use_redeem(tmp_path):
    db = store(tmp_path)
    flow, launch = ready(db)
    assert len(flow["flow"]) == 43
    raw = (tmp_path / "oauth.sqlite3").read_bytes()
    for secret in [flow["launch_ticket"], launch["state"], launch["browser_binding"], GRANT["access_token"]]:
        assert secret.encode() not in raw
    metadata = store(tmp_path).status("owner-a", flow["flow"], now=104)
    assert metadata["stage"] == "ready"
    assert "access_token" not in str(metadata)
    assert store(tmp_path).redeem("owner-a", flow["flow"], PROOF, now=104) == GRANT
    with pytest.raises(FlowRejected):
        db.redeem("owner-a", flow["flow"], PROOF, now=104)
    with sqlite3.connect(tmp_path / "oauth.sqlite3") as con:
        assert con.execute("SELECT grant_ciphertext FROM oauth_flows").fetchone()[0] is None


@pytest.mark.parametrize("wrong", ["owner", "proof"])
def test_bad_redemption_does_not_burn_flow(tmp_path, wrong):
    db = store(tmp_path)
    flow, _ = ready(db)
    with pytest.raises(FlowRejected, match="Authorization flow rejected"):
        db.redeem("owner-b" if wrong == "owner" else "owner-a", flow["flow"], secrets.token_urlsafe(32) if wrong == "proof" else PROOF, now=104)
    assert db.redeem("owner-a", flow["flow"], PROOF, now=104) == GRANT


def test_launch_callback_replays_and_binding(tmp_path):
    db = store(tmp_path)
    flow = begin(db)
    launch = db.launch(flow["launch_ticket"], now=101, owner="owner-a")
    with pytest.raises(FlowRejected):
        db.launch(flow["launch_ticket"], now=101, owner="owner-a")
    for provider, state, binding in [("discord", launch["state"], launch["browser_binding"]), ("alpaca", secrets.token_urlsafe(32), launch["browser_binding"]), ("alpaca", launch["state"], secrets.token_urlsafe(32))]:
        with pytest.raises(FlowRejected):
            db.claim_callback(provider, state, binding, now=102, owner="owner-a")
    assert db.claim_callback("alpaca", launch["state"], launch["browser_binding"], now=102, owner="owner-a")["flow"] == flow["flow"]
    with pytest.raises(FlowRejected):
        db.claim_callback("alpaca", launch["state"], launch["browser_binding"], now=102, owner="owner-a")


@pytest.mark.parametrize("operation", ["launch", "claim", "redeem"])
def test_parallel_one_use(tmp_path, operation):
    db = store(tmp_path)
    flow = begin(db)
    if operation != "launch":
        launch = db.launch(flow["launch_ticket"], now=101, owner="owner-a")
    if operation == "redeem":
        db.claim_callback("alpaca", launch["state"], launch["browser_binding"], now=102, owner="owner-a")
        db.complete(flow["flow"], GRANT, now=103)
    def attempt(_):
        other = store(tmp_path)
        try:
            if operation == "launch":
                other.launch(flow["launch_ticket"], now=104, owner="owner-a")
            elif operation == "claim":
                other.claim_callback("alpaca", launch["state"], launch["browser_binding"], now=104, owner="owner-a")
            else:
                other.redeem("owner-a", flow["flow"], PROOF, now=104)
            return True
        except FlowRejected:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(8))) == 1


def test_cancel_blocks_late_exchange_and_restart_does_not_retry(tmp_path):
    db = store(tmp_path)
    flow, launch = claimed(db)
    assert store(tmp_path).status("owner-a", flow["flow"], now=103)["stage"] == "exchanging"
    with pytest.raises(FlowRejected):
        db.cancel("owner-b", flow["flow"], PROOF, now=103)
    db.cancel("owner-a", flow["flow"], PROOF, now=103)
    with pytest.raises(FlowRejected):
        db.complete(flow["flow"], GRANT, now=104)
    assert db.status("owner-a", flow["flow"], now=104)["stage"] == "cancelled"


@pytest.mark.parametrize("when", [99, 163, 400])
def test_redemption_time_bounds(tmp_path, when):
    db = store(tmp_path)
    flow, _ = ready(db)
    with pytest.raises(FlowRejected):
        db.redeem("owner-a", flow["flow"], PROOF, now=when)


def test_ready_deadline_never_extends_flow(tmp_path):
    db = store(tmp_path)
    flow, _ = claimed(db)
    db.complete(flow["flow"], GRANT, now=399)
    with pytest.raises(FlowRejected):
        db.redeem("owner-a", flow["flow"], PROOF, now=400)


@pytest.mark.parametrize("field", ["flow", "owner", "challenge", "provider", "environment", "purpose"])
def test_encrypted_grant_bound_to_entire_context(tmp_path, field):
    db = store(tmp_path)
    first, _ = ready(db)
    second, _ = ready(db)
    with sqlite3.connect(tmp_path / "oauth.sqlite3") as con:
        row = con.execute("SELECT grant_ciphertext FROM oauth_flows WHERE flow=?", (first["flow"],)).fetchone()
        if field == "flow":
            con.execute("UPDATE oauth_flows SET grant_ciphertext=? WHERE flow=?", (row[0], second["flow"]))
            target, owner, proof = second["flow"], "owner-a", PROOF
        else:
            replacement = {"owner": "owner-b", "challenge": hashlib.sha256(b"X" * 43).hexdigest(), "provider": "discord", "environment": "live", "purpose": "trade"}[field]
            con.execute(f"UPDATE oauth_flows SET {field}=? WHERE flow=?", (replacement, first["flow"]))
            target, owner, proof = first["flow"], replacement if field == "owner" else "owner-a", "X" * 43 if field == "challenge" else PROOF
    with pytest.raises(FlowRejected):
        db.redeem(owner, target, proof, now=104)


def test_wrong_external_key_and_launch_ciphertext_binding(tmp_path):
    db = store(tmp_path)
    flow = begin(db)
    with pytest.raises(FlowRejected):
        FlowStore(tmp_path / "oauth.sqlite3", b"z" * 32).launch(flow["launch_ticket"], now=101, owner="owner-a")
    assert db.launch(flow["launch_ticket"], now=101, owner="owner-a")["flow"] == flow["flow"]


def test_quotas_expiry_and_bounded_cleanup(tmp_path):
    db = store(tmp_path, max_active_per_owner=2, max_active_per_challenge=1)
    begin(db)
    with pytest.raises(FlowRejected):
        begin(db)
    begin(db, challenge="a" * 64)
    with pytest.raises(FlowRejected):
        begin(db, challenge="b" * 64)
    assert db.cleanup(now=400, limit=1) == 1
    assert db.cleanup(now=400, limit=1) == 1
    begin(db, now=401)


@pytest.mark.parametrize("field,value", [("owner", ""), ("owner", "x" * 201), ("owner", "\ud800"), ("provider", "webull"), ("purpose", "trading"), ("environment", "sandbox"), ("challenge", "g" * 64), ("now", float("nan")), ("now", True)])
def test_invalid_creation_generic_errors(tmp_path, field, value):
    with pytest.raises(FlowRejected, match="^Authorization flow rejected$"):
        begin(store(tmp_path), **{field: value})


@pytest.mark.parametrize("key", [None, b"", b"a" * 31, "a" * 32])
def test_key_must_be_external_exact_bytes(tmp_path, key):
    with pytest.raises(ValueError):
        FlowStore(tmp_path / "oauth.sqlite3", key)


def test_fail_clears_sensitive_material_and_cannot_overwrite_ready(tmp_path):
    db = store(tmp_path)
    flow, _ = claimed(db)
    db.fail(flow["flow"], now=103)
    with pytest.raises(FlowRejected):
        db.complete(flow["flow"], GRANT, now=104)
    other, _ = ready(db, challenge="b" * 64)
    with pytest.raises(FlowRejected):
        db.fail(other["flow"], now=104)


def test_real_clock_checked_after_sqlite_write_lock(tmp_path, monkeypatch):
    db = store(tmp_path)
    clock = [100.0]
    monkeypatch.setattr("crier.oauth_flows.time.time", lambda: clock[0])
    flow = begin(db)
    con = sqlite3.connect(tmp_path / "oauth.sqlite3")
    con.execute("BEGIN IMMEDIATE")
    started = threading.Event()
    def launch():
        started.set()
        with pytest.raises(FlowRejected):
            db.launch(flow["launch_ticket"], owner="owner-a")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(launch)
        assert started.wait(2)
        time.sleep(0.1)
        clock[0] = 400.0
        con.commit()
        future.result(timeout=5)
    con.close()


def test_copied_launch_ciphertext_rejected_without_consuming_ticket(tmp_path):
    db = store(tmp_path)
    first, second = begin(db), begin(db)
    with sqlite3.connect(tmp_path / "oauth.sqlite3") as con:
        original = con.execute("SELECT state_ciphertext FROM oauth_flows WHERE flow=?", (second["flow"],)).fetchone()[0]
        copied = con.execute("SELECT state_ciphertext FROM oauth_flows WHERE flow=?", (first["flow"],)).fetchone()[0]
        assert original[:12] != copied[:12]
        con.execute("UPDATE oauth_flows SET state_ciphertext=? WHERE flow=?", (copied, second["flow"]))
    with pytest.raises(FlowRejected):
        db.launch(second["launch_ticket"], now=101, owner="owner-a")
    with sqlite3.connect(tmp_path / "oauth.sqlite3") as con:
        con.execute("UPDATE oauth_flows SET state_ciphertext=? WHERE flow=?", (original, second["flow"]))
    assert db.launch(second["launch_ticket"], now=101, owner="owner-a")["flow"] == second["flow"]


def test_late_completion_scrubs_expired_flow(tmp_path):
    db = store(tmp_path)
    flow, _ = claimed(db)
    with pytest.raises(FlowRejected):
        db.complete(flow["flow"], GRANT, now=400)
    assert db.status("owner-a", flow["flow"], now=400)["stage"] == "expired"
    with sqlite3.connect(tmp_path / "oauth.sqlite3") as con:
        assert con.execute("SELECT grant_ciphertext,state_ciphertext,state_hash FROM oauth_flows").fetchone() == (None, None, None)


@pytest.mark.parametrize("grant", [None, {}, [], {"token": float("nan")}, {"token": "x" * 65536}, {"token": object()}])
def test_invalid_grants_cannot_change_claim(tmp_path, grant):
    db = store(tmp_path)
    flow, _ = claimed(db)
    with pytest.raises(FlowRejected):
        db.complete(flow["flow"], grant, now=103)
    assert db.status("owner-a", flow["flow"], now=103)["stage"] == "exchanging"
    db.complete(flow["flow"], GRANT, now=103)
    with pytest.raises(FlowRejected):
        db.complete(flow["flow"], {"token": "replacement"}, now=104)
    assert db.redeem("owner-a", flow["flow"], PROOF, now=104) == GRANT


@pytest.mark.parametrize("stage", ["pending", "launched", "exchanging", "ready"])
def test_cancel_every_active_stage_scrubs_all_capabilities(tmp_path, stage):
    db = store(tmp_path)
    flow = begin(db)
    if stage != "pending":
        launch = db.launch(flow["launch_ticket"], now=101, owner="owner-a")
    if stage in ("exchanging", "ready"):
        db.claim_callback("alpaca", launch["state"], launch["browser_binding"], now=102, owner="owner-a")
    if stage == "ready":
        db.complete(flow["flow"], GRANT, now=103)
    with pytest.raises(FlowRejected):
        db.cancel("owner-a", flow["flow"], "X" * 43, now=104)
    db.cancel("owner-a", flow["flow"], PROOF, now=104)
    with sqlite3.connect(tmp_path / "oauth.sqlite3") as con:
        assert con.execute("SELECT stage,ticket_hash,state_hash,binding_hash,state_ciphertext,grant_ciphertext FROM oauth_flows").fetchone() == ("cancelled", None, None, None, None, None)


@pytest.mark.parametrize("competitor", ["complete", "redeem"])
def test_cancel_races_are_serialized_without_resurrecting_grant(tmp_path, competitor):
    db = store(tmp_path)
    flow, _ = claimed(db)
    if competitor == "redeem":
        db.complete(flow["flow"], GRANT, now=103)
    barrier = threading.Barrier(2)
    def attempt(operation):
        other = store(tmp_path)
        barrier.wait(timeout=5)
        try:
            if operation == "cancel":
                other.cancel("owner-a", flow["flow"], PROOF, now=104)
            elif operation == "complete":
                other.complete(flow["flow"], GRANT, now=104)
            else:
                other.redeem("owner-a", flow["flow"], PROOF, now=104)
            return True
        except FlowRejected:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["cancel", competitor]))
    stage = db.status("owner-a", flow["flow"], now=104)["stage"]
    assert stage in ("cancelled", "redeemed")
    assert any(outcomes)
    with pytest.raises(FlowRejected):
        db.complete(flow["flow"], GRANT, now=104)


@pytest.mark.parametrize("kwargs", [{"session_ttl": 301}, {"ready_ttl": 61}, {"max_active_per_owner": 0}, {"max_active_per_challenge": True}])
def test_invalid_configuration(tmp_path, kwargs):
    with pytest.raises(ValueError):
        store(tmp_path, **kwargs)


@pytest.mark.parametrize("bad", [None, [], "x" * 42, "x" * 44, "\ud800", "!" * 43])
def test_malformed_capabilities_use_generic_errors(tmp_path, bad):
    db = store(tmp_path)
    flow, launch = ready(db)
    calls = [lambda: db.launch(bad, now=104, owner="owner-a"), lambda: db.claim_callback("alpaca", bad, launch["browser_binding"], now=104, owner="owner-a"), lambda: db.redeem("owner-a", flow["flow"], bad, now=104), lambda: db.cancel("owner-a", flow["flow"], bad, now=104), lambda: db.status("owner-a", bad, now=104)]
    for call in calls:
        with pytest.raises(FlowRejected, match="^Authorization flow rejected$"):
            call()
    assert db.redeem("owner-a", flow["flow"], PROOF, now=104) == GRANT


@pytest.mark.parametrize("attempt_time", [101, 400])
def test_transferred_launch_ticket_rejects_different_browser_owner(tmp_path, attempt_time):
    db = store(tmp_path)
    flow = begin(db)
    with pytest.raises(FlowRejected, match="^Authorization flow rejected$"):
        db.launch(flow["launch_ticket"], now=attempt_time, owner="victim-browser-owner")
    assert db.status("owner-a", flow["flow"], now=101)["stage"] == "pending"
    assert db.launch(flow["launch_ticket"], now=101, owner="owner-a")["flow"] == flow["flow"]


@pytest.mark.parametrize("attempt_time", [102, 400])
def test_callback_requires_same_authenticated_browser_owner_without_consuming(tmp_path, attempt_time):
    db = store(tmp_path)
    flow = begin(db)
    launch = db.launch(flow["launch_ticket"], now=101, owner="owner-a")
    with pytest.raises(FlowRejected, match="^Authorization flow rejected$"):
        db.claim_callback("alpaca", launch["state"], launch["browser_binding"], now=attempt_time, owner="victim-browser-owner")
    assert db.status("owner-a", flow["flow"], now=102)["stage"] == "launched"
    assert db.claim_callback("alpaca", launch["state"], launch["browser_binding"], now=102, owner="owner-a")["flow"] == flow["flow"]
