import hashlib
import json
from pathlib import Path
import sqlite3
import time
from decimal import Decimal
from contextlib import contextmanager
from .models import Settings, Snapshot, number
from .cards import render


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, qty TEXT, price TEXT, identity TEXT);
                CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, time REAL, outcome TEXT, data TEXT);
                CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, created REAL, fill TEXT, payload TEXT,
                    status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, due REAL DEFAULT 0,
                    message_id TEXT, note TEXT, order_key TEXT);
                CREATE TABLE IF NOT EXISTS config (id TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS blocked_orders (id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS incoming_events (id TEXT PRIMARY KEY, digest TEXT NOT NULL,
                    created REAL NOT NULL, response TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, created REAL NOT NULL,
                    text TEXT NOT NULL, broker TEXT NOT NULL, environment TEXT NOT NULL,
                    status TEXT NOT NULL, draft TEXT NOT NULL, warnings TEXT NOT NULL,
                    confirmation TEXT, result TEXT);
            ''')
            if "order_key" not in {r[1] for r in db.execute("PRAGMA table_info(outbox)")}:
                db.execute("ALTER TABLE outbox ADD COLUMN order_key TEXT")
                db.execute("UPDATE outbox SET status='review',note='Legacy job requires identity reconciliation' WHERE status='pending'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def get_settings(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM config WHERE id='settings'").fetchone()
        return Settings.model_validate_json(row[0]) if row else Settings()

    def save_settings(self, settings):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO config VALUES ('settings',?)", (settings.model_dump_json(),))

    def audit(self, outcome, data):
        with self.connect() as db:
            db.execute("INSERT INTO audit(time,outcome,data) VALUES (?,?,?)", (time.time(), outcome, json.dumps(data)))

    def ingest(self, snap: Snapshot, settings: Settings, baseline=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.ingest_in_transaction(db, snap, settings, baseline)

    def ingest_in_transaction(self, db, snap: Snapshot, settings: Settings, baseline=False, *, execution_price=None):
        """Caller must own a transaction; used for atomic receipt/event acceptance."""
        if execution_price is not None:
            if (snap.broker != "alpaca" or snap.verification != "broker_reported"
                    or not isinstance(execution_price, Decimal)
                    or not execution_price.is_finite() or execution_price <= 0):
                raise ValueError("Exact execution price requires trusted Alpaca fill evidence")
        key = order_key(snap)
        identity_parts = [snap.symbol, snap.category, snap.side, snap.intent]
        # Keep existing broker watermarks compatible; do not merge manual and broker evidence.
        if snap.verification != "broker_reported":
            identity_parts.append(snap.verification)
        identity = json.dumps(identity_parts)
        data = snap.model_dump(mode="json")
        old = db.execute("SELECT * FROM orders WHERE id=?", (key,)).fetchone()
        outcome, fill = "queued", None
        old_qty = Decimal(old["qty"]) if old else Decimal(0)
        old_price = Decimal(old["price"]) if old else Decimal(0)
        # Reconcile exact broker evidence with an earlier manual receipt.
        # Never emit a duplicate fill; disagreement still requires review.
        manual_identity = json.dumps(identity_parts + ["user_confirmed"])
        if (old and snap.verification == "broker_reported"
                and old["identity"] == manual_identity
                and not db.execute("SELECT 1 FROM blocked_orders WHERE id=?", (key,)).fetchone()
                and snap.cumulative_qty == old_qty
                and snap.average_price == old_price):
            db.execute("UPDATE orders SET identity=? WHERE id=?", (identity, key))
            db.execute("INSERT INTO audit(time,outcome,data) VALUES (?,?,?)",
                       (time.time(), "reconciled", json.dumps(data)))
            return {"outcome": "reconciled", "fill": None}
        if db.execute("SELECT 1 FROM blocked_orders WHERE id=?", (key,)).fetchone(): outcome = "review"
        elif old and identity != old["identity"]: outcome = "review"
        elif snap.cumulative_qty < old_qty: outcome = "stale"
        elif snap.cumulative_qty == old_qty:
            outcome = "duplicate" if snap.average_price == old_price else "review"
        else:
            quantity = snap.cumulative_qty - old_qty
            price = (snap.average_price * snap.cumulative_qty - old_price * old_qty) / quantity
            if execution_price is not None:
                # Snapshot averages round to 8 decimals. Permit only the maximum
                # notional error from rounding BOTH cumulative averages (half an
                # eighth-decimal unit each), never an arbitrary price override.
                error_bound = (snap.cumulative_qty + old_qty) * Decimal("0.000000005")
                if abs((execution_price - price) * quantity) > error_bound:
                    raise ValueError("Execution price disagrees with cumulative notional")
                price = execution_price
            if price <= 0: outcome = "review"
            else:
                # Persist watermark and frozen public payload in one transaction.
                ref = hashlib.sha256(f"{key}:{number(snap.cumulative_qty)}".encode()).hexdigest()[:16]
                fill = {k: v for k, v in data.items() if k not in ("account", "order_id", "average_price")}
                fill.update(quantity=number(quantity), price=number(price), contract=snap.contract,
                            expiration=snap.expiration, reference=ref)
                db.execute("INSERT OR REPLACE INTO orders VALUES (?,?,?,?)",
                           (key, number(snap.cumulative_qty), number(snap.average_price), identity))
                if baseline: outcome = "baseline"
                else:
                    try:
                        payload = render(fill, settings)
                        db.execute("INSERT INTO outbox(id,created,fill,payload,order_key) VALUES (?,?,?,?,?)",
                                   (ref, time.time(), json.dumps(fill), json.dumps(payload), key))
                    except ValueError:
                        outcome = "review"
                        db.execute("INSERT INTO outbox(id,created,fill,payload,status,note,order_key) VALUES (?,?,?,?,?,?,?)",
                                   (ref, time.time(), json.dumps(fill), "{}", "review", "Template does not support this fill; no message sent", key))
        if outcome == "review":
            db.execute("INSERT OR IGNORE INTO blocked_orders VALUES (?)", (key,))
            db.execute("UPDATE outbox SET status='review',note='Source order disputed; awaiting reconciliation' WHERE order_key=? AND status='pending'", (key,))
        db.execute("INSERT INTO audit(time,outcome,data) VALUES (?,?,?)", (time.time(), outcome, json.dumps(data)))
        return {"outcome": outcome, "fill": fill}

    def history(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM outbox ORDER BY created DESC LIMIT 100").fetchall()
        return [dict(r) | {"fill": json.loads(r["fill"]), "payload": json.loads(r["payload"])} for r in rows]

    def claim(self, job_id=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pause = db.execute("SELECT value FROM config WHERE id='discord_retry_at'").fetchone()
            if pause and float(pause[0]) > time.time(): return None
            # Only one sender may own any job at a time, even across processes.
            if db.execute("SELECT 1 FROM outbox WHERE status='sending'").fetchone(): return None
            row = db.execute("SELECT * FROM outbox WHERE status='pending' AND due<=? AND (? IS NULL OR id=?) AND NOT EXISTS (SELECT 1 FROM blocked_orders WHERE blocked_orders.id=outbox.order_key) ORDER BY created LIMIT 1", (time.time(),job_id,job_id)).fetchone()
            if row:
                db.execute("UPDATE outbox SET status='sending', attempts=attempts+1, due=? WHERE id=?", (time.time(), row["id"]))
                return dict(row) | {"payload": json.loads(row["payload"])}

    def complete(self, id, status, note="", delay=0, message_id=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if status == "pending" and db.execute(
                "SELECT 1 FROM outbox JOIN blocked_orders ON blocked_orders.id=outbox.order_key WHERE outbox.id=?", (id,)
            ).fetchone():
                status, note = "review", "Source order disputed during delivery; awaiting reconciliation"
            db.execute("UPDATE outbox SET status=?,note=?,due=?,message_id=? WHERE id=?",
                       (status, note, time.time() + delay, message_id, id))

    def throttle(self, seconds):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO config VALUES ('discord_retry_at',?)", (str(time.time() + seconds),))

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE outbox SET status='uncertain',note='Service restarted during delivery; check Discord before resolving' WHERE status='sending'")

    def review_count(self):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM audit WHERE outcome IN ('review','invalid')").fetchone()[0]


def order_key(snap):
    return hashlib.sha256(json.dumps([snap.broker, snap.environment, snap.account, snap.order_id]).encode()).hexdigest()
