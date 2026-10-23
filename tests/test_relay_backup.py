import json
import os
from pathlib import Path
import sqlite3
import threading

import pytest

from crier.intent_relay import IntentRelay
from crier.lock import AlreadyRunningError, single_process
from crier.quick_connect import ConnectionService
from crier.relay_backup import (BackupError, DB_NAME, create_backup, main,
                                restore_backup, verify_backup)
from test_intent_relay import event


def checkpoint(path):
    from contextlib import closing
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        db.execute('PRAGMA journal_mode=DELETE')


@pytest.fixture
def relay(tmp_path):
    return IntentRelay(tmp_path / 'data' / DB_NAME)


def test_complete_relay_survives_restore(relay, tmp_path):
    service = ConnectionService(relay)
    pair = relay.create('Backup channel', 'paper')
    invitation = service.invite(pair['host_token'])
    receiver = service.receive(invitation['code'])
    pending = service.invite(pair['host_token'])
    instruction = event()
    relay.publish(pair['host_token'], instruction)
    snapshot = create_backup(relay.path.parent, tmp_path / 'backups')
    metadata = verify_backup(snapshot)
    text = (snapshot / 'manifest.json').read_text()
    assert pair['host_token'] not in text and pending['code'] not in text
    assert metadata['database'] == DB_NAME
    restored = restore_backup(snapshot, tmp_path / 'restored')
    result = IntentRelay(restored)
    assert result.channels() == relay.channels()
    assert result.read(receiver['token'], 0)['events'][0]['event'] == instruction.to_dict()
    assert ConnectionService(result).receive(pending['code'])['role'] == 'follower'
    assert len(ConnectionService(result).receivers(pair['host_token'])) == 2


def test_online_backup_during_wal_writes(relay, tmp_path):
    pair = relay.create('Concurrent', 'paper')
    stop = threading.Event()
    started = threading.Event()
    failures = []
    def writer():
        try:
            while not stop.is_set():
                relay.publish(pair['host_token'], event())
                started.set()
        except Exception as error:
            failures.append(error)
    thread = threading.Thread(target=writer)
    thread.start()
    try:
        assert started.wait(5)
        snapshot = create_backup(relay.path.parent, tmp_path / 'backups')
        assert verify_backup(snapshot)['bytes'] > 0
        with sqlite3.connect(snapshot / DB_NAME) as saved:
            assert saved.execute('SELECT COUNT(*) FROM intents').fetchone()[0] > 0
    finally:
        stop.set()
        thread.join(10)
    assert not thread.is_alive()
    assert not failures


def test_corruption_refused_before_existing_database_changed(relay, tmp_path):
    relay.create('Original', 'paper')
    snapshot = create_backup(relay.path.parent, tmp_path / 'backups')
    original = relay.path.read_bytes()
    with (snapshot / DB_NAME).open('ab') as handle:
        handle.write(b'corrupt')
    with pytest.raises(BackupError, match='checksum'):
        restore_backup(snapshot, relay.path.parent, overwrite=True)
    assert relay.path.read_bytes() == original
    # A matching malicious manifest does not bypass SQLite validation.
    (snapshot / DB_NAME).write_bytes(b'not sqlite')
    from hashlib import sha256
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    manifest.update(bytes=10, sha256=sha256(b'not sqlite').hexdigest())
    (snapshot / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(BackupError, match='integrity'):
        verify_backup(snapshot)


def test_restore_lock_overwrite_and_sidecar_guards(relay, tmp_path):
    snapshot = create_backup(relay.path.parent, tmp_path / 'backups')
    with single_process(relay.path.parent / 'connection-server.lock'):
        with pytest.raises(AlreadyRunningError):
            restore_backup(snapshot, relay.path.parent, overwrite=True)
    with pytest.raises(BackupError, match='exists'):
        restore_backup(snapshot, relay.path.parent)
    checkpoint(relay.path)
    sidecar = Path(str(relay.path) + '-wal')
    sidecar.write_bytes(b'keep')
    original = relay.path.read_bytes()
    with pytest.raises(BackupError, match='sidecars'):
        restore_backup(snapshot, relay.path.parent, overwrite=True)
    assert sidecar.read_bytes() == b'keep'
    assert relay.path.read_bytes() == original
    sidecar.unlink()
    assert restore_backup(snapshot, relay.path.parent, overwrite=True) == relay.path


def test_failed_staged_restore_preserves_original(relay, tmp_path, monkeypatch):
    import crier.relay_backup as module
    snapshot = create_backup(relay.path.parent, tmp_path / 'backups')
    checkpoint(relay.path)
    original = relay.path.read_bytes()
    def fail(source, target):
        target.write_bytes(b'partial')
        raise OSError('disk full')
    monkeypatch.setattr(module, '_snapshot', fail)
    with pytest.raises(OSError):
        restore_backup(snapshot, relay.path.parent, overwrite=True)
    assert relay.path.read_bytes() == original
    assert not list(relay.path.parent.glob('.restore-*'))


def test_retention_and_private_permissions(relay, tmp_path):
    directory = tmp_path / 'backups'
    unrelated = directory / 'notes.txt'
    first = create_backup(relay.path.parent, directory, retain=2)
    unrelated.write_text('retain me')
    second = create_backup(relay.path.parent, directory, retain=2)
    third = create_backup(relay.path.parent, directory, retain=2)
    assert not first.exists()
    assert second.exists() and third.exists() and unrelated.exists()
    if os.name != 'nt':
        assert directory.stat().st_mode & 0o777 == 0o700
        assert (third / DB_NAME).stat().st_mode & 0o777 == 0o600
    with pytest.raises(BackupError, match='positive'):
        create_backup(relay.path.parent, directory, retain=0)


def test_reject_other_database_and_symlinks(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    with sqlite3.connect(data / DB_NAME) as db:
        db.execute('CREATE TABLE secret(value)')
    with pytest.raises(BackupError, match='relay database'):
        create_backup(data, tmp_path / 'backups')
    link = tmp_path / 'link'
    try:
        link.symlink_to(data, target_is_directory=True)
    except OSError:
        pytest.skip('Symlink creation requires platform privileges')
    with pytest.raises(BackupError, match='Symlink'):
        create_backup(link, tmp_path / 'backups')


def test_cli(relay, tmp_path, capsys):
    directory = tmp_path / 'backups'
    main(['backup', '--data-dir', str(relay.path.parent), '--backup-dir', str(directory)])
    snapshot = Path(capsys.readouterr().out.strip())
    main(['verify', str(snapshot)])
    assert 'verified' in capsys.readouterr().out
    main(['restore', str(snapshot), '--data-dir', str(tmp_path / 'restored')])
    assert (tmp_path / 'restored' / DB_NAME).is_file()


def test_restore_sync_failure_rolls_back_existing_database(relay, tmp_path, monkeypatch):
    import crier.relay_backup as module
    snapshot = create_backup(relay.path.parent, tmp_path / 'backups')
    relay.create('After backup', 'paper')
    checkpoint(relay.path)
    original = relay.path.read_bytes()
    def fail(path):
        raise OSError('sync failed')
    monkeypatch.setattr(module, '_sync_directory', fail)
    with pytest.raises(OSError):
        restore_backup(snapshot, relay.path.parent, overwrite=True)
    assert relay.path.read_bytes() == original
