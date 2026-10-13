import json
import pytest
from crier.config import Config
from crier.store import Store
from crier import monitors
from crier.lock import single_process


def test_none_does_not_start_process(tmp_path):
    assert monitors.start_monitor(Config(data_dir=tmp_path,token="a"*32)) is None
    monitors.stop_monitor(None)


def test_stop_monitor_terminates_and_joins():
    calls=[]
    class Child:
        alive=True
        def is_alive(self): return self.alive
        def terminate(self): calls.append("terminate"); self.alive=False
        def join(self,timeout): calls.append("join")
    monitors.stop_monitor(Child())
    assert calls==["terminate","join"]


def test_duplicate_monitor_cannot_overwrite_owner_state(tmp_path,monkeypatch):
    from crier import webull
    config=Config(data_dir=tmp_path,token="a"*32,monitor="webull")
    store=Store(tmp_path/'crier.sqlite3')
    owner={"state":"observing","updated":100,"broker":"webull"}
    with store.connect() as db:
        db.execute("INSERT INTO config VALUES ('observer',?)",(json.dumps(owner),))
    with single_process(tmp_path/'observer.lock'):
        with pytest.raises(SystemExit): monitors.run_monitor(config)
    with store.connect() as db:
        assert json.loads(db.execute("SELECT value FROM config WHERE id='observer'").fetchone()[0])==owner


def test_failed_monitor_records_sanitized_error(tmp_path,monkeypatch):
    from crier import webull
    def fail(config): raise ValueError('secret-token-should-not-be-logged')
    monkeypatch.setattr(webull,'observe',fail)
    config=Config(data_dir=tmp_path,token="a"*32,monitor="webull")
    with pytest.raises(SystemExit): monitors.run_monitor(config)
    with Store(tmp_path/'crier.sqlite3').connect() as db:
        state=db.execute("SELECT value FROM config WHERE id='observer'").fetchone()[0]
        assert 'secret-token' not in state and json.loads(state)['state']=='error'
