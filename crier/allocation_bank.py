"""Durable host-owned lots, account reservations and non-reusable trade IDs.

Only the managed broker bridge may feed authoritative broker snapshots. This
module never places an order. Removing an ID from active does not erase its
history, source identity, order IDs or duplicate protection.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, localcontext, ROUND_DOWN
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from .host_allocation import Scope, Funds, Usage, Allocation, preview, _amount, _format

TERMINAL={"filled","canceled","expired","rejected","replaced","skipped"}
STATUSES=TERMINAL|{"unknown","new","accepted","pending_new","accepted_for_bidding","partially_filled","done_for_day","pending_cancel","pending_replace","stopped","suspended","calculated"}
_LOCKS={};_LOCK_GUARD=threading.Lock()

class BankConflict(ValueError): pass


def scope_key(scope):
    if not isinstance(scope,Scope):raise BankConflict("Explicit bank account scope required")
    return hashlib.sha256(json.dumps([scope.broker,scope.account,scope.environment],separators=(",",":")).encode()).hexdigest()


def _units(value):
    if type(value) is not int or not 0<=value<=1000000000:raise BankConflict("Invalid bank unit count")
    return value


def _identity(value):
    if not isinstance(value,str) or not 1<=len(value)<=128 or any(ord(c)<33 or ord(c)>126 for c in value):raise BankConflict("Invalid bank identity")
    return value


class AccountBank:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS bank_meta(id INTEGER PRIMARY KEY,version INTEGER NOT NULL);
            INSERT OR IGNORE INTO bank_meta VALUES(1,1);
            CREATE TABLE IF NOT EXISTS bank_accounts(scope TEXT PRIMARY KEY,broker TEXT,account TEXT,environment TEXT,available TEXT,equity TEXT,blocked TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS bank_policies(scope TEXT,route TEXT,asset TEXT,data TEXT,PRIMARY KEY(scope,route,asset));
            CREATE TABLE IF NOT EXISTS bank_pnl(scope TEXT,route TEXT,asset TEXT,value TEXT,PRIMARY KEY(scope,route,asset));
            CREATE TABLE IF NOT EXISTS bank_ids(id INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT,route TEXT,trade TEXT,symbol TEXT,asset TEXT,multiplier INTEGER,state TEXT,invalid INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT '',UNIQUE(scope,route,trade));
            CREATE TABLE IF NOT EXISTS bank_active(id INTEGER PRIMARY KEY REFERENCES bank_ids(id));
            CREATE TABLE IF NOT EXISTS bank_orders(cid TEXT PRIMARY KEY,bank_id INTEGER REFERENCES bank_ids(id),scope TEXT,event TEXT,side TEXT,ordinal INTEGER,quantity INTEGER,price TEXT,fee TEXT,status TEXT,broker_id TEXT,filled INTEGER,filled_cost TEXT,charge TEXT,basis TEXT,fee_booked INTEGER,dispatch_started INTEGER NOT NULL DEFAULT 0,UNIQUE(scope,event,side,ordinal));
            CREATE TABLE IF NOT EXISTS bank_sources(scope TEXT,route TEXT,path TEXT,pairing TEXT,PRIMARY KEY(scope,route,path));
            CREATE TABLE IF NOT EXISTS bank_fees(scope TEXT,route TEXT,asset TEXT,value TEXT,PRIMARY KEY(scope,route,asset));
            CREATE TABLE IF NOT EXISTS bank_baselines(scope TEXT,symbol TEXT,quantity INTEGER,PRIMARY KEY(scope,symbol));
            CREATE TABLE IF NOT EXISTS bank_inventory_initialized(scope TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS bank_audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,bank_id INTEGER,kind TEXT,at TEXT,detail TEXT);
            """)
            if db.execute("SELECT version FROM bank_meta WHERE id=1").fetchone()[0]!=1:raise BankConflict("Unsupported ID bank schema; preserve bank and journals")

    @contextmanager
    def db(self,write=False):
        db=sqlite3.connect(self.path,timeout=5);db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON");db.execute("PRAGMA synchronous=FULL")
        try:
            if write:db.execute("BEGIN IMMEDIATE")
            with db:yield db
        finally:db.close()

    @contextmanager
    def locked(self,scope):
        from .lock import single_process
        key=(str(self.path.resolve()),scope_key(scope))
        with _LOCK_GUARD:lock=_LOCKS.setdefault(key,threading.RLock())
        folder=self.path.parent/"bank-locks";folder.mkdir(exist_ok=True)
        with lock, single_process(folder/(key[1]+".lock")):yield

    @staticmethod
    def client_id(scope,route,trade,event,side,ordinal):
        for value in (route,trade,event):_identity(value)
        if side not in ("buy","sell"):raise BankConflict("Invalid order side")
        _units(ordinal)
        raw=json.dumps([scope_key(scope),route,trade,event,side,ordinal],separators=(",",":"))
        return "sc-"+hashlib.sha256(raw.encode()).hexdigest()[:40]

    def _account(self,db,key):
        row=db.execute("SELECT * FROM bank_accounts WHERE scope=?",(key,)).fetchone()
        if row is None:raise BankConflict("Account ID bank is not enabled")
        return row

    def enabled(self,scope):
        with self.db() as db:return db.execute("SELECT 1 FROM bank_accounts WHERE scope=?",(scope_key(scope),)).fetchone() is not None

    def enable(self,scope,cash,equity):
        cash=_amount(cash);equity=_amount(equity)
        if equity<=0:raise BankConflict("Verified positive account equity required")
        with self.db(True) as db:
            db.execute("INSERT OR IGNORE INTO bank_accounts(scope,broker,account,environment,available,equity) VALUES(?,?,?,?,?,?)",(scope_key(scope),scope.broker,scope.account,scope.environment,_format(min(cash,equity)),_format(equity)))
        return self.account(scope)

    def account(self,scope):
        with self.db() as db:return dict(self._account(db,scope_key(scope)))

    def block(self,scope,reason):
        _identity(reason)
        with self.db(True) as db:
            self._account(db,scope_key(scope))
            db.execute("UPDATE bank_accounts SET blocked=? WHERE scope=?",(reason,scope_key(scope)))

    def configure(self,scope,route,asset,policy,fee="0"):
        _identity(route)
        if asset not in ("stock","option") or type(policy) is not dict or set(policy)!={"mode","value"}:raise BankConflict("Invalid bank allocation")
        Allocation(**policy).amount();_amount(fee)
        with self.db(True) as db:
            self._account(db,scope_key(scope))
            db.execute("INSERT OR REPLACE INTO bank_policies VALUES(?,?,?,?)",(scope_key(scope),route,asset,json.dumps(policy,sort_keys=True)))
            db.execute("INSERT OR REPLACE INTO bank_fees VALUES(?,?,?,?)",(scope_key(scope),route,asset,fee))

    def policy(self,scope,route,asset):
        with self.db() as db:return self._policy(db,scope_key(scope),route,asset)

    def _policy(self,db,key,route,asset):
        row=db.execute("SELECT data FROM bank_policies WHERE scope=? AND route=? AND asset=?",(key,route,asset)).fetchone()
        return json.loads(row[0]) if row else {"mode":"dollars","value":"0"}

    def _audit(self,db,identity,kind,**detail):
        db.execute("INSERT INTO bank_audit(bank_id,kind,at,detail) VALUES(?,?,?,?)",(identity,kind,datetime.now(timezone.utc).isoformat(),json.dumps(detail,sort_keys=True)))

    def _lot(self,db,identity):
        orders=[dict(row) for row in db.execute("SELECT * FROM bank_orders WHERE bank_id=? ORDER BY rowid",(identity,))]
        units=sum(row["filled"]*(1 if row["side"]=="buy" else -1) for row in orders)
        basis=sum((_amount(row["filled_cost"]) if row["side"]=="buy" else -_amount(row["basis"]) for row in orders),Decimal(0))
        pending_buy=sum(row["quantity"]-row["filled"] for row in orders if row["side"]=="buy" and row["status"] not in TERMINAL)
        pending_exit=sum(row["quantity"]-row["filled"] for row in orders if row["side"]=="sell" and row["status"] not in TERMINAL)
        exposure=sum((_amount(row["charge"])-(_amount(row["fee"]) if row["fee_booked"] else 0) if row["side"]=="buy" else -_amount(row["basis"]) for row in orders),Decimal(0))
        if units<0 or basis<0 or pending_exit>units:raise BankConflict("Contradictory host lot ownership")
        return dict(units=units,basis=basis,pending_buy_units=pending_buy,pending_exit_units=pending_exit,exposure=max(Decimal(0),exposure),orders=orders)

    def _retire(self,db,identity,reason):
        lot=self._lot(db,identity)
        if lot["units"] or any(row["status"] not in TERMINAL for row in lot["orders"]):raise BankConflict("ID retains holdings or unresolved orders")
        db.execute("UPDATE bank_ids SET state='closed',invalid=1,reason=? WHERE id=?",(reason,identity))
        db.execute("DELETE FROM bank_active WHERE id=?",(identity,))
        self._audit(db,identity,"retired",reason=reason)

    def retire(self,scope,route,trade,reason):
        _identity(reason)
        with self.db(True) as db:
            row=db.execute("SELECT * FROM bank_ids WHERE scope=? AND route=? AND trade=?",(scope_key(scope),route,trade)).fetchone()
            if row is None:raise BankConflict("Unknown owned ID")
            self._retire(db,row["id"],reason)

    def invalidate(self,scope,route,trade,reason):
        _identity(reason)
        with self.db(True) as db:
            row=db.execute("SELECT id FROM bank_ids WHERE scope=? AND route=? AND trade=?",(scope_key(scope),route,trade)).fetchone()
            if row is None:return
            db.execute("UPDATE bank_ids SET invalid=1,reason=? WHERE id=?",(reason,row[0]))
            lot=self._lot(db,row[0])
            if not lot["units"] and all(order["status"] in TERMINAL for order in lot["orders"]):self._retire(db,row[0],reason)

    def _summary(self,db,row):
        value=dict(row);lot=self._lot(db,row["id"])
        value.update(units=lot["units"],basis=_format(lot["basis"]),pending_buy_units=lot["pending_buy_units"],pending_exit_units=lot["pending_exit_units"])
        return value

    def active(self,scope,route=None):
        with self.db() as db:
            rows=db.execute("SELECT i.* FROM bank_ids i JOIN bank_active a ON a.id=i.id WHERE i.scope=? ORDER BY i.id",(scope_key(scope),)).fetchall()
            return [self._summary(db,row) for row in rows if route is None or row["route"]==route]

    def history(self,scope,identity):
        with self.db() as db:
            row=db.execute("SELECT * FROM bank_ids WHERE scope=? AND id=?",(scope_key(scope),identity)).fetchone()
            if row is None:raise BankConflict("Unknown account ID")
            return self._summary(db,row)

    def orders(self,scope,active_only=True):
        with self.db() as db:
            sql="SELECT o.* FROM bank_orders o"+(" JOIN bank_active a ON a.id=o.bank_id" if active_only else "")+" WHERE o.scope=? ORDER BY o.rowid"
            return [dict(row) for row in db.execute(sql,(scope_key(scope),))]

    def reserve(self,scope,route,trade,event,cid,symbol,asset,multiplier,side,quantity,price,fee,*,cash,equity,ordinal):
        for value in (route,trade,event,cid,symbol):_identity(value)
        _units(quantity);_units(ordinal)
        if quantity<1 or side not in ("buy","sell") or asset not in ("stock","option") or type(multiplier) is not int or multiplier!=(100 if asset=="option" else 1):raise BankConflict("Unsupported bank order")
        price_value=_amount(price);fee_value=_amount(fee);cash_value=_amount(cash);equity_value=_amount(equity)
        if price_value<=0 or equity_value<=0:raise BankConflict("Verified bounded valuation required")
        key=scope_key(scope)
        with self.db(True) as db, localcontext() as context:
            context.prec=80
            account=self._account(db,key)
            existing=db.execute("SELECT o.*,i.route,i.trade,i.symbol,i.asset,i.multiplier FROM bank_orders o JOIN bank_ids i ON i.id=o.bank_id WHERE o.cid=?",(cid,)).fetchone()
            if existing:
                if any(existing[name]!=value for name,value in dict(scope=key,route=route,trade=trade,event=event,side=side,quantity=quantity,price=price,fee=fee,symbol=symbol,asset=asset,multiplier=multiplier,ordinal=ordinal).items()):raise BankConflict("Order ID reused with changed intent")
                return dict(existing,existing=True)
            if db.execute("SELECT 1 FROM bank_orders WHERE scope=? AND event=? AND side=? AND ordinal=?",(key,event,side,ordinal)).fetchone():raise BankConflict("Source event already allocated to this account")
            row=db.execute("SELECT * FROM bank_ids WHERE scope=? AND route=? AND trade=?",(key,route,trade)).fetchone()
            if row and (row["state"]=="closed" or (side=="buy" and row["invalid"])):raise BankConflict("Retired or invalid source ID cannot reopen")
            if row and (row["symbol"],row["asset"],row["multiplier"])!=(symbol,asset,multiplier):raise BankConflict("Owned instrument changed")
            if side=="buy":
                if account["blocked"]:raise BankConflict("Account needs reconciliation")
                host_units=0;host_notional=Decimal(0)
                for owned in db.execute("SELECT i.* FROM bank_ids i JOIN bank_active a ON a.id=i.id WHERE i.scope=? AND i.route=? AND i.asset=?",(key,route,asset)):
                    lot=self._lot(db,owned["id"]);host_units+=lot["units"]+lot["pending_buy_units"];host_notional+=lot["exposure"]
                config=self._policy(db,key,route,asset)
                pnl_row=db.execute("SELECT value FROM bank_pnl WHERE scope=? AND route=? AND asset=?",(key,route,asset)).fetchone()
                pnl=Decimal(pnl_row[0]) if pnl_row else Decimal(0)
                allocation=Allocation(**config)
                if allocation.mode!="units" and pnl<0:
                    cap=allocation.amount() if allocation.mode=="dollars" else (equity_value*allocation.amount()/100).quantize(Decimal(".01"),rounding=ROUND_DOWN)
                    allocation=Allocation("dollars",_format(max(Decimal(0),cap+pnl)))
                now=datetime.now(timezone.utc)
                result=preview(scope=scope,host_id=route,funds=Funds(scope,equity,_format(min(cash_value,_amount(account["available"]))),now,"bank-admission","USD"),usage=Usage(scope,route,host_units,_format(host_notional),asset),pool=allocation,sizing=Allocation("units",str(quantity)),asset=asset,multiplier=multiplier,buy_limit=price,fee_reserve=fee,max_units=1000,now=now)
                if result["decision"]!="eligible":raise BankConflict("Allocation unavailable: "+result["reason"])
                charge=quantity*price_value*multiplier+fee_value
            else:
                if row is None:raise BankConflict("No holdings owned by this host ID")
                lot=self._lot(db,row["id"])
                if quantity>lot["units"]-lot["pending_exit_units"]:raise BankConflict("Exit exceeds unreserved owned holdings")
                # Exit fees are covered by confirmed sale proceeds, never by
                # borrowing another host's cash or spending an unfilled sale.
                if fee_value>price_value*multiplier:raise BankConflict("Exit limit cannot cover its fee reserve")
                charge=Decimal(0)
            if row is None:
                identity=db.execute("INSERT INTO bank_ids(scope,route,trade,symbol,asset,multiplier,state) VALUES(?,?,?,?,?,?,'active')",(key,route,trade,symbol,asset,multiplier)).lastrowid
                db.execute("INSERT INTO bank_active VALUES(?)",(identity,))
            else:identity=row["id"]
            db.execute("UPDATE bank_accounts SET available=?,equity=? WHERE scope=?",(_format(_amount(account["available"])-charge),equity,key))
            db.execute("INSERT INTO bank_orders VALUES(?,?,?,?,?,?,?,?,?,'unknown',NULL,0,'0',?,'0',0,0)",(cid,identity,key,event,side,ordinal,quantity,price,fee,_format(charge)))
            self._audit(db,identity,"reserved",cid=cid,side=side,quantity=quantity,charge=_format(charge),policy=self._policy(db,key,route,asset))
            return dict(db.execute("SELECT o.*,i.trade FROM bank_orders o JOIN bank_ids i ON i.id=o.bank_id WHERE cid=?",(cid,)).fetchone(),existing=False)

    def _pnl(self,db,row,delta):
        old=db.execute("SELECT value FROM bank_pnl WHERE scope=? AND route=? AND asset=?",(row["scope"],row["route"],row["asset"])).fetchone()
        value=(Decimal(old[0]) if old else Decimal(0))+delta
        db.execute("INSERT OR REPLACE INTO bank_pnl VALUES(?,?,?,?)",(row["scope"],row["route"],row["asset"],_format(value)))

    def observe(self,scope,cid,snapshot):
        key=scope_key(scope)
        try:
            with self.db(True) as db, localcontext() as context:
                context.prec=80
                row=db.execute("SELECT o.*,i.route,i.trade,i.symbol,i.asset,i.multiplier,i.invalid,i.state FROM bank_orders o JOIN bank_ids i ON i.id=o.bank_id WHERE cid=? AND o.scope=?",(cid,key)).fetchone()
                if row is None:raise BankConflict("Unknown bank order proof")
                try:
                    filled=Decimal(str(snapshot["filled_qty"]));qty=Decimal(str(snapshot["qty"]))
                    status=snapshot["status"];broker_id=snapshot["id"]
                    valid=(snapshot["client_order_id"]==cid and snapshot["symbol"]==row["symbol"] and snapshot["side"]==row["side"] and qty==row["quantity"] and filled.is_finite() and filled==filled.to_integral_value() and row["filled"]<=filled<=row["quantity"] and status in STATUSES and status!="unknown" and isinstance(broker_id,str) and bool(broker_id.strip()) and (not row["broker_id"] or row["broker_id"]==broker_id))
                    if not valid:raise BankConflict("Conflicting broker order proof")
                    filled=int(filled)
                    if status=="filled" and filled!=row["quantity"]:raise BankConflict("Incomplete filled order")
                    if row["status"] in TERMINAL and status not in TERMINAL:raise BankConflict("Terminal order reopened")
                    avg=_amount(str(snapshot["filled_avg_price"])) if filled else Decimal(0)
                    if filled and avg<=0:raise BankConflict("Missing verified execution price")
                    cost=filled*avg*row["multiplier"]
                    old_cost=_amount(row["filled_cost"]);delta_units=filled-row["filled"];delta_cost=cost-old_cost
                    if delta_cost<0 or (delta_units==0 and delta_cost!=0):raise BankConflict("Broker corrected prior execution cost")
                    if row["side"]=="buy" and delta_cost>delta_units*_amount(row["price"])*row["multiplier"]:raise BankConflict("Fill exceeds reserved limit")
                    if row["side"]=="sell" and delta_cost<delta_units*_amount(row["price"])*row["multiplier"]:raise BankConflict("Sale violates its limit")
                except (KeyError,TypeError,ArithmeticError,ValueError) as exc:
                    raise BankConflict("Unusable broker order evidence") from exc
                if (status,broker_id,filled,cost)==(row['status'],row['broker_id'],row['filled'],old_cost):
                    return
                account=self._account(db,key);cash=_amount(account["available"])
                if row["status"] in TERMINAL and delta_units:
                    db.execute("UPDATE bank_accounts SET blocked='late_terminal_fill' WHERE scope=?",(key,))
                    db.execute("UPDATE bank_ids SET state='active',invalid=1,reason='late_terminal_fill' WHERE id=?",(row["bank_id"],))
                    db.execute("INSERT OR IGNORE INTO bank_active VALUES(?)",(row["bank_id"],))
                if row["side"]=="buy":
                    rest=0 if status in TERMINAL else row["quantity"]-filled
                    charge=cost+rest*_amount(row["price"])*row["multiplier"]+(_amount(row["fee"]) if filled or rest else Decimal(0))
                    cash+=_amount(row["charge"])-charge
                    basis=Decimal(0)
                else:
                    lot=self._lot(db,row["bank_id"])
                    if delta_units>lot["units"]:raise BankConflict("Broker sale exceeds owned units")
                    released=lot["basis"] if delta_units==lot["units"] else (lot["basis"]*delta_units/lot["units"]).quantize(Decimal(".00000001"),rounding=ROUND_DOWN) if delta_units else Decimal(0)
                    basis=_amount(row["basis"])+released
                    new_fee=_amount(row["fee"]) if filled and not row["fee_booked"] else Decimal(0)
                    cash+=min(released,max(Decimal(0),delta_cost-new_fee))
                    self._pnl(db,row,delta_cost-released)
                    charge=Decimal(0)
                if filled and not row["fee_booked"]:self._pnl(db,row,-_amount(row["fee"]))
                db.execute("UPDATE bank_orders SET status=?,broker_id=?,filled=?,filled_cost=?,charge=?,basis=?,fee_booked=? WHERE cid=?",(status,broker_id,filled,_format(cost),_format(charge),_format(basis),int(bool(filled) or row["fee_booked"]),cid))
                db.execute("UPDATE bank_accounts SET available=? WHERE scope=?",(_format(max(Decimal(0),cash)),key))
                if cash<0:db.execute("UPDATE bank_accounts SET blocked='capacity_deficit' WHERE scope=?",(key,))
                self._audit(db,row["bank_id"],"broker_evidence",cid=cid,status=status,filled=filled,cost=_format(cost))
                current=db.execute("SELECT * FROM bank_ids WHERE id=?",(row["bank_id"],)).fetchone()
                lot=self._lot(db,row["bank_id"])
                if not lot["units"] and all(o["status"] in TERMINAL for o in lot["orders"]):
                    if current["invalid"] or any(o["side"]=="sell" and o["filled"] for o in lot["orders"]):self._retire(db,row["bank_id"],current["reason"] or "sold")
        except (BankConflict,ValueError,ArithmeticError) as exc:
            self.block(scope,"broker_evidence_conflict")
            raise BankConflict("Broker evidence needs reconciliation; reservations retained") from exc

    def not_submitted(self,scope,cid,*,definitive=False):
        with self.db() as db:
            row=db.execute("SELECT * FROM bank_orders WHERE scope=? AND cid=?",(scope_key(scope),cid)).fetchone()
            if row is None:raise BankConflict("Unknown bank reservation")
            if row["broker_id"] or row["filled"] or (row["dispatch_started"] and not definitive):raise BankConflict("Cannot erase broker evidence")
        self.observe(scope,cid,dict(id="local-no-post:"+cid,client_order_id=cid,symbol=self.history(scope,row["bank_id"])["symbol"],side=row["side"],qty=str(row["quantity"]),filled_qty="0",filled_avg_price=None,status="rejected"))
        with self.db(True) as db:
            owned=db.execute("SELECT * FROM bank_ids WHERE id=?",(row["bank_id"],)).fetchone()
            lot=self._lot(db,row["bank_id"])
            if not lot["units"] and all(o["status"] in TERMINAL for o in lot["orders"]):self._retire(db,row["bank_id"],"not_submitted")

    def inventory(self,scope,positions):
        key=scope_key(scope)
        if type(positions) is not dict:raise BankConflict("Verified account positions required")
        for symbol,qty in positions.items():_identity(symbol);_units(qty)
        mismatch=False
        with self.db(True) as db:
            self._account(db,key)
            owned={}
            for row in db.execute("SELECT i.* FROM bank_ids i JOIN bank_active a ON a.id=i.id WHERE scope=?",(key,)):
                lot=self._lot(db,row["id"])
                owned[row["symbol"]]=owned.get(row["symbol"],0)+lot["units"]
            baseline={r[0]:r[1] for r in db.execute("SELECT symbol,quantity FROM bank_baselines WHERE scope=?",(key,))}
            # Establish external holdings once, during verified setup. Being
            # flat later is not permission to absorb a late or manual fill.
            pending=db.execute("SELECT 1 FROM bank_orders WHERE scope=? AND status NOT IN ('filled','canceled','expired','rejected','replaced','skipped') LIMIT 1",(key,)).fetchone()
            initialized=db.execute("SELECT 1 FROM bank_inventory_initialized WHERE scope=?",(key,)).fetchone()
            if not initialized and not any(owned.values()) and not pending:
                db.execute("DELETE FROM bank_baselines WHERE scope=?",(key,))
                db.executemany("INSERT INTO bank_baselines VALUES(?,?,?)",[(key,symbol,qty) for symbol,qty in positions.items()])
            else:
                for symbol in set(positions)|set(owned)|set(baseline):
                    if positions.get(symbol,0)!=owned.get(symbol,0)+baseline.get(symbol,0):mismatch=True
                if mismatch:db.execute("UPDATE bank_accounts SET blocked='position_discrepancy' WHERE scope=? AND blocked=''",(key,))
                else:db.execute("UPDATE bank_accounts SET blocked='' WHERE scope=? AND blocked='position_discrepancy'",(key,))
            db.execute("INSERT OR IGNORE INTO bank_inventory_initialized VALUES(?)",(key,))
        if mismatch:raise BankConflict("Broker inventory differs; no host ownership was reassigned")

    def rebase_if_flat(self,scope,cash,equity):
        cash=_amount(cash);equity=_amount(equity)
        with self.db(True) as db:
            row=self._account(db,scope_key(scope))
            if row["blocked"]:return False
            if db.execute("SELECT 1 FROM bank_ids i JOIN bank_active a ON a.id=i.id WHERE i.scope=? LIMIT 1",(scope_key(scope),)).fetchone():return False
            db.execute("UPDATE bank_accounts SET available=?,equity=? WHERE scope=?",(_format(min(cash,equity)),_format(equity),scope_key(scope)))
            return True


    def order(self,scope,cid):
        with self.db() as db:
            row=db.execute("SELECT * FROM bank_orders WHERE scope=? AND cid=?",(scope_key(scope),cid)).fetchone()
            return dict(row) if row else None

    def mark_dispatching(self,scope,cid):
        with self.db(True) as db:
            result=db.execute("UPDATE bank_orders SET dispatch_started=1 WHERE scope=? AND cid=? AND dispatch_started=0 AND status='unknown' AND broker_id IS NULL AND filled=0",(scope_key(scope),cid))
            if result.rowcount!=1:raise BankConflict("Order dispatch already started or changed; reconcile without resending")

    def fee(self,scope,route,asset):
        with self.db() as db:
            row=db.execute("SELECT value FROM bank_fees WHERE scope=? AND route=? AND asset=?",(scope_key(scope),route,asset)).fetchone()
            return row[0] if row else "0"

    def register_journal(self,scope,route,path,pairing):
        _identity(route);_identity(pairing)
        root=self.path.parent.resolve();path=Path(path).resolve()
        if not path.is_relative_to(root):raise BankConflict("Journal must remain inside the account bank profile")
        relative=path.relative_to(root).as_posix()
        with self.db(True) as db:
            existing=db.execute("SELECT pairing FROM bank_sources WHERE scope=? AND route=? AND path=?",(scope_key(scope),route,relative)).fetchone()
            if existing and existing[0]!=pairing:raise BankConflict("Bank journal pairing changed")
            db.execute("INSERT OR IGNORE INTO bank_sources VALUES(?,?,?,?)",(scope_key(scope),route,relative,pairing))

    def journals(self,scope):
        with self.db() as db:rows=list(db.execute("SELECT path FROM bank_sources WHERE scope=?",(scope_key(scope),)))
        root=self.path.parent.resolve();result=[]
        for row in rows:
            path=(root/row[0]).resolve()
            if not path.is_relative_to(root) or not path.is_file():raise BankConflict("Retained account journal is unavailable; preserve recovery evidence")
            result.append(path)
        return result

    def history_rows(self,scope,limit=100):
        if type(limit) is not int or not 1<=limit<=1000:raise BankConflict("Bounded history limit required")
        with self.db() as db:return [self._summary(db,row) for row in db.execute("SELECT * FROM bank_ids WHERE scope=? ORDER BY id DESC LIMIT ?",(scope_key(scope),limit))]
