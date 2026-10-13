"""Read-only experimental Webull adapter. No order submission methods are called."""
from datetime import datetime, timezone
import json
import os
import time
import hashlib
import re

from .models import Snapshot, number
from .store import Store, order_key


def normalize(payload, account, environment="sandbox"):
    if not isinstance(payload, dict): raise ValueError("Expected one order event")
    if payload.get("account_id") != account: raise ValueError("Unexpected account")
    if payload.get("legs") or payload.get("combo_order_id"):
        raise ValueError("Multi-leg orders require a separate adapter")
    scene = payload.get("scene_type")
    if scene not in ("FILLED", "FINAL_FILLED"): return None
    order_id = payload.get("order_id")
    if type(order_id) not in (str, int) or (type(order_id) is int and order_id <= 0):
        raise ValueError("Missing or invalid order identity")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(order_id)):
        raise ValueError("Malformed order identity")
    # filled_price must have been verified as cumulative average for this account/feed.
    return Snapshot(account=account, environment=environment, order_id=str(order_id), category=payload["category"],
                    symbol=payload["symbol"], side=payload["side"], cumulative_qty=payload["filled_qty"],
                    average_price=payload["filled_price"], occurred_at=payload["filled_time"],
                    status="FILLED" if scene == "FINAL_FILLED" else "PARTIAL")


def quiet_event_client(key, secret, region, host):
    from webull.trade.trade_events_client import TradeEventsClient
    from webull.trade.events import events_pb2 as pb
    from webull.trade.events.signature_composer import calc_signature
    from webull.core.auth.algorithm import sha_hmac256_new

    class QuietClient(TradeEventsClient):
        def _build_request(self, app_key, app_secret, accounts):
            # SDK 3.0.3 prints signed authentication metadata in the base method.
            # Construct the same protobuf using the official signer without those prints.
            request = pb.SubscribeRequest(subscribeType=5, timestamp=int(time.time() * 1000), accounts=accounts)
            _, metadata = calc_signature(app_key, app_secret, request, sha_hmac256_new)
            return request, metadata

        def _easy_handler(self, response):
            if self.heartbeat: self.heartbeat(response.eventType)
            return super()._easy_handler(response)

    client = QuietClient(key, secret, region, host=host)
    client.heartbeat = None
    return client


def credentials():
    values = [os.getenv(k, "") for k in ("WEBULL_APP_KEY", "WEBULL_APP_SECRET", "WEBULL_ACCOUNT_ID")]
    if not all(values): raise ValueError("Set WEBULL_APP_KEY, WEBULL_APP_SECRET and WEBULL_ACCOUNT_ID on the server")
    if os.getenv("WEBULL_REGION", "us") != "us": raise ValueError("Only US accounts are implemented in this adapter")
    return values


def enrollment_key(environment, account):
    return "enrollment:" + hashlib.sha256(json.dumps([environment, account]).encode()).hexdigest()


def enroll(db, manifest):
    """Operator-verified initial balances. All validation happens before one atomic write."""
    if manifest.get("complete_open_orders") is not True:
        raise ValueError("Baseline must attest to all open orders at captured_at")
    stamp = datetime.fromisoformat(manifest["captured_at"].replace("Z", "+00:00"))
    if stamp.tzinfo is None: raise ValueError("Baseline time must include timezone")
    account, environment = manifest["account"], manifest["environment"]
    if not account or environment not in ("sandbox", "production"): raise ValueError("Invalid enrollment scope")
    snapshots = [Snapshot.model_validate(s) for s in manifest["snapshots"]]
    keys = set()
    for snap in snapshots:
        if snap.account != account or snap.environment != environment: raise ValueError("Baseline scope mismatch")
        if snap.occurred_at > stamp: raise ValueError("Baseline cannot include fills after capture time")
        if order_key(snap) in keys: raise ValueError("Duplicate order in baseline")
        keys.add(order_key(snap))
    key = enrollment_key(environment, account)
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM config WHERE id=?", (key,)).fetchone():
            raise ValueError("Already enrolled; do not overwrite active watermarks with historical balances")
        for snap in snapshots:
            if con.execute("SELECT 1 FROM orders WHERE id=?", (order_key(snap),)).fetchone():
                raise ValueError("Order already observed; reconcile rather than overwriting its balance")
            identity = json.dumps([snap.symbol, snap.category, snap.side, snap.intent])
            con.execute("INSERT INTO orders VALUES (?,?,?,?)", (order_key(snap), number(snap.cumulative_qty), number(snap.average_price), identity))
        con.execute("INSERT INTO config VALUES (?,?)", (key, stamp.isoformat()))
        con.execute("INSERT INTO audit(time,outcome,data) VALUES (?,?,?)", (time.time(), "enrolled", json.dumps({"scope": key, "orders": len(snapshots)})))


def observe(config):
    from webull.trade.events.types import EVENT_TYPE_ORDER, EVENT_TYPE_OPTION
    from webull.trade.events import events_pb2 as pb
    key, secret, account = credentials()
    verified = config.webull_verified and os.getenv("CRIER_WEBULL_PRICE_MODE") == "cumulative_average"
    db = Store(config.data_dir / "crier.sqlite3")
    env = os.getenv("WEBULL_ENV", "sandbox")
    if env not in ("sandbox", "production"): raise ValueError("WEBULL_ENV must be sandbox or production")
    host = "events-api.sandbox.webull.com" if env == "sandbox" else "events-api.webull.com"
    client = quiet_event_client(key, secret, "us", host)
    session_key = enrollment_key(env, account)
    with db.connect() as con:
        row = con.execute("SELECT value FROM config WHERE id=?", (session_key,)).fetchone()
    started = datetime.fromisoformat(row[0]) if row else None
    verified = verified and started is not None

    def state(value):
        with db.connect() as con:
            con.execute("INSERT OR REPLACE INTO config VALUES ('observer',?)", (json.dumps({"state": value, "updated": time.time(), "verified": verified, "environment": env}),))

    def heartbeat(event_type):
        if event_type in (pb.AuthError, pb.SubscribeExpired, pb.NumOfConnExceed): state("error")
        elif event_type in (pb.Ping, pb.SubscribeSuccess, EVENT_TYPE_ORDER, EVENT_TYPE_OPTION):
            state("observing" if verified else "capture_only")

    def on_message(event_type, subscribe_type, payload, raw):
        if event_type not in (EVENT_TYPE_ORDER, EVENT_TYPE_OPTION): return
        # SDK payloads only; never write request metadata or secrets to logs.
        db.audit("observed", payload)
        if not verified: return
        try:
            snap = normalize(payload, account, env)
            if snap:
                db.ingest(snap, db.get_settings(), baseline=snap.occurred_at < started)
        except (ValueError, KeyError, TypeError):
            db.audit("invalid", {"reason": "Unsupported or incomplete Webull event; inspect the private observed record"})

    client.heartbeat = heartbeat
    client.on_events_message = on_message
    client.on_log = lambda level, message: state("reconnecting") if level >= 30 else None
    state("connecting")
    try: client.do_subscribe([account])
    finally: state("stopped")


def export_history(output):
    """Read-only evidence for manual-app coverage; never replays history to Discord."""
    from webull.core.client import ApiClient
    from webull.trade.trade_client import TradeClient
    key, secret, account = credentials()
    api = ApiClient(key, secret, "us")
    env = os.getenv("WEBULL_ENV", "sandbox")
    if env not in ("sandbox", "production"): raise ValueError("Unknown Webull environment")
    api.add_endpoint("us", "api.sandbox.webull.com" if env == "sandbox" else "api.webull.com")
    trade = TradeClient(api)
    # Export one page verbatim: preserve pagination metadata and do not guess response shape.
    response = trade.order_v3.list_order_history(account)
    if response.status_code != 200: raise ValueError(f"Webull history request failed: HTTP {response.status_code}")
    with open(output, "x", encoding="utf-8") as f:
        os.chmod(output, 0o600)
        json.dump(response.json(), f, indent=2)
