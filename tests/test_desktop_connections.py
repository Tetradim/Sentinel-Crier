import asyncio
import json
import pytest
from crier.desktop_connections import DesktopConnections
from crier.desktop_runtime import DesktopSession

PAIR = dict(url='https://relay.example', token='t'*40, environment='paper', role='follower')

class Broker:
    def __init__(self, environment, key, secret, account): self.closed = False
    def close(self): self.closed = True

async def lookup(environment, key, secret):
    await asyncio.sleep(0)
    return key

def factory(folder, **kwargs):
    return DesktopSession(folder, account_lookup=lookup, broker_factory=Broker, start_workers=False, **kwargs)

def test_registry_migration_selection_and_restart(tmp_path):
    evidence = tmp_path / 'journal' / 'old-evidence'
    evidence.parent.mkdir()
    evidence.write_text('unresolved')
    manager = DesktopConnections(tmp_path, factory)
    original = manager.selected
    assert manager.session.folder == tmp_path
    second = manager.add('../second')
    assert manager.session.folder == tmp_path / 'connections' / second
    assert evidence.read_text() == 'unresolved'
    restarted = DesktopConnections(tmp_path, factory)
    assert restarted.selected == second
    assert restarted.sessions[original].folder == tmp_path
    assert all(session.broker is None for session in restarted.sessions.values())

def test_collision_persists_after_disconnect_and_restart(tmp_path):
    async def run():
        manager = DesktopConnections(tmp_path, factory)
        first = manager.selected
        second = manager.add('Second')
        results = await asyncio.gather(*(manager.invoke(identity, 'connect', json.dumps(PAIR), 'same-account', 'secret')
                                        for identity in (first, second)), return_exceptions=True)
        assert sum(isinstance(result, ValueError) for result in results) == 1
        await manager.invoke(first, 'disconnect')
        with pytest.raises(ValueError, match='another route'):
            await manager.invoke(second, 'connect', json.dumps(PAIR), 'same-account', 'secret')
        restarted = DesktopConnections(tmp_path, factory)
        with pytest.raises(ValueError, match='another route'):
            await restarted.invoke(second, 'connect', json.dumps(PAIR), 'same-account', 'secret')
    asyncio.run(run())

def test_selection_and_disconnect_leave_other_route_running(tmp_path):
    async def run():
        manager = DesktopConnections(tmp_path, factory)
        first = manager.selected
        second = manager.add('Second')
        for identity, account in ((first, 'account-a'), (second, 'account-b')):
            await manager.invoke(identity, 'connect', json.dumps(PAIR), account, 'secret')
        assert manager.sessions[first].device.folder != manager.sessions[second].device.folder
        manager.select(first)
        await manager.invoke(second, 'disconnect')
        assert manager.sessions[first].broker is not None
        assert not manager.sessions[first].status()['execution']['settings']['enabled']
        await manager.invoke(first, 'disconnect_all')
        assert all(session.broker is None for session in manager.sessions.values())
    asyncio.run(run())

def test_worker_captures_route_before_loop_submission(tmp_path):
    from crier.desktop_runtime import DesktopWorker
    worker = DesktopWorker(tmp_path)
    try:
        first = worker.connections.selected
        second = worker.connections.add('Second')
        worker.connections.select(first)
        async def identity():
            await asyncio.sleep(0.01)
            return first
        worker.connections.sessions[first].marker = identity
        future = worker.call('marker')
        worker.connections.select(second)
        assert future.route_id == first
        assert future.result(timeout=3) == first
    finally:
        worker.close()


def test_duplicate_legacy_and_unknown_owner_fail_closed(tmp_path):
    manager = DesktopConnections(tmp_path, factory)
    second = manager.add('Second')
    with manager.database() as db:
        db.execute('UPDATE routes SET legacy=1 WHERE id=?', (second,))
    with pytest.raises(ValueError, match='legacy'):
        DesktopConnections(tmp_path, factory)


def test_existing_credentials_import_account_claim_without_moving_journal(tmp_path):
    from crier.device_secrets import save_secret
    save_secret(tmp_path / 'desktop-credentials.secret', json.dumps(dict(pair=PAIR, account='old-account', key='synthetic', secret='synthetic')))
    manager = DesktopConnections(tmp_path, factory)
    second = manager.add('Second')
    async def run():
        with pytest.raises(ValueError, match='another route'):
            await manager.invoke(second, 'connect', json.dumps(PAIR), 'old-account', 'secret')
    asyncio.run(run())
    assert (tmp_path / 'desktop-credentials.secret').exists()

@pytest.mark.parametrize('restart', [False, True])
def test_rejected_saved_account_change_does_not_reserve_candidate(tmp_path, restart):
    async def run():
        manager = DesktopConnections(tmp_path, factory)
        first = manager.selected
        await manager.invoke(first, 'connect', json.dumps(PAIR), 'account-a', 'secret')
        await manager.invoke(first, 'disconnect')
        with pytest.raises(ValueError):
            await manager.invoke(first, 'connect', json.dumps(PAIR), 'account-b', 'secret')
        if restart: manager = DesktopConnections(tmp_path, factory)
        second = manager.add('Account B')
        await manager.invoke(second, 'connect', json.dumps(PAIR), 'account-b', 'secret')
        await manager.invoke(second, 'disconnect_all')
    asyncio.run(run())


def test_retained_engine_pin_reserves_account_without_credentials(tmp_path):
    import sqlite3
    journal = tmp_path / 'journal'
    journal.mkdir()
    path = journal / 'intent-retained.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE intent_pin(id INTEGER PRIMARY KEY, environment TEXT, account TEXT)')
        db.execute("INSERT INTO intent_pin VALUES (1,'paper','historical-account')")
    manager = DesktopConnections(tmp_path, factory)
    second = manager.add('Second')
    manager = DesktopConnections(tmp_path, factory)
    async def run():
        with pytest.raises(ValueError, match='another route'):
            await manager.invoke(second, 'connect', json.dumps(PAIR), 'historical-account', 'secret')
    asyncio.run(run())
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT account FROM intent_pin').fetchone()[0] == 'historical-account'

@pytest.mark.parametrize('kind', ['unreadable', 'multiple', 'invalid_environment'])
def test_unverifiable_journal_pin_blocks_startup(tmp_path, kind):
    import sqlite3
    journal = tmp_path / 'journal'
    journal.mkdir()
    path = journal / 'intent-retained.sqlite3'
    if kind == 'unreadable':
        path.write_bytes(b'not a sqlite journal')
    else:
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE intent_pin(id INTEGER PRIMARY KEY, environment TEXT, account TEXT)')
            db.execute('INSERT INTO intent_pin VALUES (1,?,?)', ('invalid' if kind == 'invalid_environment' else 'paper', 'account-a'))
            if kind == 'multiple': db.execute("INSERT INTO intent_pin VALUES (2,'paper','account-b')")
    with pytest.raises(ValueError): DesktopConnections(tmp_path, factory)
    assert path.exists()


def test_close_confirms_other_running_route_when_selected_disconnected(monkeypatch):
    from types import SimpleNamespace
    from crier.desktop import DesktopApp
    app = DesktopApp.__new__(DesktopApp)
    app.closing = False
    app.connected = False
    app.presence = None
    app.root = object()
    app.worker = SimpleNamespace(connections=SimpleNamespace(sessions={'other': SimpleNamespace(broker=object())}))
    prompts = []
    monkeypatch.setattr('crier.desktop.messagebox.askokcancel', lambda *args, **kwargs: prompts.append(args) or False)
    app.close(quit=True)
    assert prompts and 'All connections' in prompts[0][1]
    assert not app.closing
