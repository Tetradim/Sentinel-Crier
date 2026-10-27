import json
import sqlite3
import pytest
from crier import update_recovery as recovery


def test_roundtrip_ciphertext_and_wal(tmp_path):
    profile = tmp_path / 'profile'; profile.mkdir()
    secret = b'DPAPI synthetic ciphertext\x00'; (profile / 'secret.bin').write_bytes(secret)
    db = sqlite3.connect(profile / 'state.sqlite3')
    db.execute('PRAGMA journal_mode=WAL'); db.execute('CREATE TABLE data(value)'); db.execute('INSERT INTO data VALUES (42)'); db.commit()
    backup = recovery.create_backup(profile, tmp_path / 'backups')
    db.close()
    metadata = recovery.validate_backup(backup)
    assert metadata['schema'] == 1
    restored = recovery.restore_backup(backup, tmp_path / 'restored')
    assert (restored / 'secret.bin').read_bytes() == secret
    with sqlite3.connect(restored / 'state.sqlite3') as conn:
        assert conn.execute('SELECT value FROM data').fetchone() == (42,)
    with pytest.raises(ValueError): recovery.restore_backup(backup, restored)
    (backup / 'secret.bin').write_bytes(b'corrupt')
    with pytest.raises(ValueError): recovery.validate_backup(backup)


def test_generation_refuses_unsupported_without_mutation(tmp_path):
    recovery.ensure_profile_compatible(tmp_path)
    marker = tmp_path / 'profile-format.json'
    marker.write_text('{"schema":1,"generation":99}')
    before = marker.read_bytes()
    with pytest.raises(ValueError): recovery.ensure_profile_compatible(tmp_path)
    assert marker.read_bytes() == before


def test_reject_inside_profile_and_unknown_manifest(tmp_path):
    profile = tmp_path / 'profile'; profile.mkdir()
    with pytest.raises(ValueError): recovery.create_backup(profile, profile / 'backups')
    backup = recovery.create_backup(profile, tmp_path / 'backups')
    manifest = backup / 'manifest.json'
    data = json.loads(manifest.read_text()); data['schema'] = 99
    manifest.chmod(0o600); manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError): recovery.validate_backup(backup)


def test_lock_enforced(tmp_path):
    from crier.lock import single_process, AlreadyRunningError
    with single_process(tmp_path / 'desktop.lock'):
        with pytest.raises(AlreadyRunningError): recovery.create_backup(tmp_path, tmp_path.parent / (tmp_path.name + '-backups'))


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/escape', 'dir\\escape', 'CON', 'name.', 'a:b', 'bad?name', 'bad\x00name'])
def test_manifest_rejects_unsafe_names(tmp_path, name):
    manifest = {'schema': 1, 'files': [{'name': name, 'size': 0, 'sha256': '0' * 64}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Unsafe'):
        recovery.validate_backup(tmp_path)


def test_backup_refuses_symlink_without_copying_target(tmp_path):
    profile = tmp_path / 'profile'; profile.mkdir()
    outside = tmp_path / 'outside'; outside.write_text('synthetic')
    try: (profile / 'link').symlink_to(outside)
    except OSError: pytest.skip('Symlinks unavailable to this Windows token')
    with pytest.raises(ValueError): recovery.create_backup(profile, tmp_path / 'backups')
    assert not (tmp_path / 'backups').exists()


def test_unknown_profile_marker_preserved(tmp_path):
    marker = tmp_path / 'profile-format.json'; marker.write_text('{"schema":99,"generation":1}')
    before = marker.read_bytes()
    with pytest.raises(ValueError): recovery.ensure_profile_compatible(tmp_path)
    assert marker.read_bytes() == before


def test_size_limit_applies_before_snapshot(tmp_path, monkeypatch):
    profile = tmp_path / 'profile'; profile.mkdir(); (profile / 'data').write_bytes(b'1234')
    monkeypatch.setattr(recovery, 'MAX_BYTES', 2)
    with pytest.raises(ValueError): recovery.create_backup(profile, tmp_path / 'backups')
    assert not (tmp_path / 'backups').exists()


def test_failed_snapshot_leaves_no_partial_backup(tmp_path, monkeypatch):
    profile = tmp_path / 'profile'; profile.mkdir()
    monkeypatch.setattr(recovery, 'MAX_MANIFEST', 1)
    with pytest.raises(ValueError): recovery.create_backup(profile, tmp_path / 'backups')
    assert list((tmp_path / 'backups').iterdir()) == []
