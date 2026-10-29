"""Synthetic multi-route ownership tests; no broker/relay network is used."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from crier.desktop_runtime import DesktopSession
from crier.desktop_connections import DesktopConnections


class PaperBroker:
    def __init__(self, environment, key, secret, account):
        self.environment, self.account = environment, account
        self.orders, self.sent = {}, []
    def verify(self, environment):
        assert environment == self.environment
        return self.account
    def lookup(self, cid): return self.orders.get(cid)
    def submit(self, order):
        self.sent.append(dict(order))
        row = dict(order, id=str(uuid4()), status="filled", filled_qty=order["qty"], filled_avg_price="0.20")
        self.orders[order["client_order_id"]] = row
        return row
    def position(self, symbol): return 100
    def cancel(self, identity): raise AssertionError("No cancel expected")
    def close(self): pass


def factory(folder, **kwargs):
    async def identity(environment, key, secret): return key
    return DesktopSession(folder, account_lookup=identity, broker_factory=PaperBroker, start_workers=False, **kwargs)


def pair(token):
    return json.dumps(dict(url="https://relay.example", token=token*40, environment="paper", role="follower"))


def instruction(action="enter", sequence=1, trade_id=None):
    now=datetime.now(timezone.utc)
    return dict(version=1,event_id=str(uuid4()),trade_id=trade_id or str(uuid4()),sequence=sequence,
                action=action,environment="paper",symbol="SPY261218C00750000",asset="option",quantity=2,
                limit_price="0.20",created_at=now.isoformat(),expires_at=(now+timedelta(seconds=25)).isoformat())


def test_fanout_to_two_accounts_keeps_exits_and_duplicates_independent(tmp_path):
    async def run():
        manager=DesktopConnections(tmp_path,session_factory=factory)
        first=manager.selected
        second=manager.add("Other account")
        try:
            await manager.invoke(first,"connect",pair("a"),"account-one","synthetic")
            await manager.invoke(second,"connect",pair("b"),"account-two","synthetic")
            one,two=manager.sessions[first],manager.sessions[second]
            event=instruction()
            for session in (one,two):
                session.device.engine.save_settings({"enabled":True})
                session.device.engine.accept(event);session.device.engine.tick()
                session.device.engine.accept(event);session.device.engine.tick()
                assert len(session.broker.sent)==1
            # Selection is presentation only; an exit on host one cannot sell account two.
            manager.select(second)
            exit_event=instruction("exit",2,event["trade_id"])
            one.device.engine.accept(exit_event);one.device.engine.tick();one.device.engine.tick()
            assert [x["side"] for x in one.broker.sent]==["buy","sell"]
            assert [x["side"] for x in two.broker.sent]==["buy"]
            assert one.broker.sent[-1]["qty"]=="2"
            assert one.folder!=two.folder and one.device.engine.path!=two.device.engine.path
        finally:
            for session in manager.sessions.values(): await session.shutdown()
    asyncio.run(run())


def test_worker_runtime_log_does_not_compete_with_legacy_rotation(tmp_path):
    from crier.desktop_runtime import DesktopWorker
    worker=DesktopWorker(tmp_path)
    try:
        assert worker.error_log.folder!=worker.session.error_log.folder
    finally:
        worker.close()


def test_credentialless_retained_history_cannot_be_rebound_or_poison_another_account(tmp_path):
    import sqlite3
    import pytest
    journal=tmp_path/"journal";journal.mkdir()
    evidence=journal/"intent-retained.sqlite3"
    with sqlite3.connect(evidence) as db:
        db.execute("CREATE TABLE intent_pin(id INTEGER PRIMARY KEY, environment TEXT, account TEXT)")
        db.execute("INSERT INTO intent_pin VALUES (1,'paper','historical')")
    async def run():
        manager=DesktopConnections(tmp_path,session_factory=factory)
        first=manager.selected
        try:
            with pytest.raises(ValueError,match="retained"):
                await manager.invoke(first,"connect",pair("a"),"new-account","synthetic")
            assert not manager.sessions[first].credentials.exists()
            second=manager.add("New account")
            await manager.invoke(second,"connect",pair("b"),"new-account","synthetic")
            assert manager.sessions[second].account=="new-account"
        finally:
            for session in manager.sessions.values(): await session.shutdown()
    asyncio.run(run())
