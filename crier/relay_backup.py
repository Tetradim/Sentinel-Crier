"""Consistent, private SQLite relay snapshots and offline, atomic restore.

Run ``python -m crier.relay_backup --help``. Snapshots contain credentials.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from uuid import uuid4

from .lock import single_process

DB_NAME = 'intent-relay.sqlite3'
MANIFEST = 'manifest.json'
SNAPSHOT_NAME = re.compile(r'relay-\d{8}T\d{12}Z-[a-f0-9]{12}')
REQUIRED_TABLES = {'channels', 'intents', 'receivers'}


class BackupError(ValueError):
    """Snapshot or destination is unsafe or invalid."""


def _safe_path(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            attributes = getattr(part.lstat(), 'st_file_attributes', 0)
        except FileNotFoundError:
            attributes = 0
        if part.is_symlink() or attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
            raise BackupError('Symlink and junction paths are not supported')
    return path


def _private_directory(path):
    path = _safe_path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise BackupError('Expected a directory')
    if os.name == 'nt':
        # Windows chmod cannot restrict ACLs. Use the current token's SID and
        # remove inherited access before any snapshot data is written.
        import csv
        result = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'],
                                check=True, capture_output=True, text=True)
        sid = next(csv.reader(result.stdout.splitlines()))[1]
        if not re.fullmatch(r'S-1-[\d-]+', sid):
            raise BackupError('Could not determine snapshot owner')
        import ctypes
        from ctypes import wintypes
        advapi = ctypes.WinDLL('advapi32', use_last_error=True)
        descriptor = ctypes.c_void_p()
        convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
        convert.restype = wintypes.BOOL
        set_security = advapi.SetFileSecurityW
        set_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        set_security.restype = wintypes.BOOL
        if not convert('D:P(A;OICI;FA;;;' + sid + ')', 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not set_security(str(path), 0x80000004, descriptor):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            ctypes.windll.kernel32.LocalFree(descriptor)
    else:
        path.chmod(0o700)
    return path


def _connect(path):
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=30)


def _integrity(path):
    try:
        with closing(_connect(path)) as db:
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise BackupError('SQLite integrity check failed')
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED_TABLES <= tables:
                raise BackupError('Database is not a relay database')
            columns = {
                'channels': {'id', 'host_digest', 'follower_digest', 'revoked'},
                'intents': {'cursor', 'channel', 'event_id', 'payload'},
                'receivers': {'id', 'channel', 'token_digest', 'revoked'},
            }
            for table, expected in columns.items():
                actual = {row[1] for row in db.execute('PRAGMA table_info(' + table + ')')}
                if not expected <= actual:
                    raise BackupError('Database is not a relay database')
    except sqlite3.Error:
        raise BackupError('SQLite integrity check failed') from None


def _digest(path):
    digest = sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_directory(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _snapshot(source, target):
    with closing(_connect(source)) as src, closing(sqlite3.connect(target)) as dest:
        src.backup(dest, pages=256, sleep=0.01)
        dest.execute('PRAGMA journal_mode=DELETE')
    target.chmod(0o600)
    _integrity(target)
    with target.open('r+b') as handle:
        os.fsync(handle.fileno())


def verify_backup(snapshot):
    """Validate checksum, manifest, relay schema, and SQLite integrity."""
    snapshot = _safe_path(snapshot)
    if not snapshot.is_dir():
        raise BackupError('Snapshot must be a directory')
    db = _safe_path(snapshot / DB_NAME)
    manifest = _safe_path(snapshot / MANIFEST)
    if {p.name for p in snapshot.iterdir()} != {DB_NAME, MANIFEST}:
        raise BackupError('Unexpected snapshot contents')
    if not db.is_file() or not manifest.is_file() or manifest.stat().st_size > 4096:
        raise BackupError('Missing or invalid snapshot files')
    try:
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        valid = (isinstance(metadata, dict) and metadata.get('version') == 1
                 and metadata.get('database') == DB_NAME
                 and metadata.get('bytes') == db.stat().st_size
                 and metadata.get('sha256') == _digest(db))
    except (ValueError, OSError):
        raise BackupError('Invalid snapshot manifest') from None
    if not valid:
        raise BackupError('Snapshot checksum or manifest mismatch')
    _integrity(db)
    return metadata


def _prune(backup_dir, retain):
    snapshots = []
    for path in backup_dir.iterdir():
        if SNAPSHOT_NAME.fullmatch(path.name):
            # Never delete unknown, corrupt, or redirected directories.
            verify_backup(path)
            snapshots.append(path)
    for old in sorted(snapshots, reverse=True)[retain:]:
        shutil.rmtree(old)


def create_backup(data_dir, backup_dir, retain=7):
    """Online backup; return the atomically published snapshot directory.

    Retention counts complete snapshots. Failure never removes the source DB.
    """
    if isinstance(retain, bool) or not isinstance(retain, int) or retain < 1:
        raise BackupError('Retention must be a positive integer')
    source = _safe_path(Path(data_dir) / DB_NAME)
    if not source.is_file():
        raise BackupError('Relay database does not exist')
    for suffix in ('-wal', '-shm', '-journal'):
        _safe_path(str(source) + suffix)
    backup_dir = _private_directory(backup_dir)
    if backup_dir == source.parent:
        raise BackupError('Use a separate backup directory')
    lock = _safe_path(backup_dir / 'backup.lock')
    with single_process(lock):
        staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=backup_dir))
        try:
            target = staging / DB_NAME
            _snapshot(source, target)
            stamp = datetime.now(timezone.utc)
            metadata = dict(version=1, database=DB_NAME,
                            created_at=stamp.isoformat(), bytes=target.stat().st_size,
                            sha256=_digest(target))
            manifest = staging / MANIFEST
            with manifest.open('x', encoding='utf-8') as handle:
                json.dump(metadata, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            manifest.chmod(0o600)
            verify_backup(staging)
            _sync_directory(staging)
            final = backup_dir / ('relay-' + stamp.strftime('%Y%m%dT%H%M%S%fZ-') + uuid4().hex[:12])
            staging.rename(final)
            _sync_directory(backup_dir)
            _prune(backup_dir, retain)
            return final
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def restore_backup(snapshot, data_dir, overwrite=False):
    """Restore offline under the service lock, replacing only the known DB.

    An existing WAL/SHM must be checkpointed by the stopped service first.
    Restore never deletes sidecars or modifies the old DB before replacement.
    """
    snapshot = _safe_path(snapshot)
    verify_backup(snapshot)
    data_dir = _safe_path(data_dir)
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = _safe_path(data_dir / DB_NAME)
    if target == snapshot / DB_NAME:
        raise BackupError('Cannot restore over a snapshot')
    lock = _safe_path(data_dir / 'connection-server.lock')
    with single_process(lock):
        if target.exists() and not overwrite:
            raise BackupError('Relay database exists; use --overwrite explicitly')
        if target.exists() and not target.is_file():
            raise BackupError('Relay destination must be a regular file')
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = _safe_path(str(target) + suffix)
            if sidecar.exists():
                raise BackupError('SQLite sidecars exist; stop and checkpoint the relay before restore')
        staging = Path(tempfile.mkdtemp(prefix='.restore-', dir=data_dir))
        _private_directory(staging)
        temporary = staging / DB_NAME
        original = staging / 'original.sqlite3'
        rollback_failed = False
        try:
            _snapshot(snapshot / DB_NAME, temporary)
            # Verify again before publishing to catch accidental source changes.
            verify_backup(snapshot)
            if target.exists():
                os.link(target, original)
            replaced = False
            try:
                os.replace(temporary, target)
                replaced = True
                _sync_directory(data_dir)
            except OSError:
                if replaced:
                    if original.exists():
                        try:
                            os.replace(original, target)
                        except OSError:
                            rollback_failed = True
                            raise
                    else:
                        target.unlink()
                raise
            return target
        finally:
            if not rollback_failed:
                shutil.rmtree(staging)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    backup = commands.add_parser('backup', help='Create an online SQLite snapshot')
    backup.add_argument('--data-dir', default=os.getenv('CRIER_DATA_DIR', 'data'))
    backup.add_argument('--backup-dir', required=True)
    backup.add_argument('--retain', type=int, default=7)
    verify = commands.add_parser('verify', help='Verify a snapshot directory')
    verify.add_argument('snapshot')
    restore = commands.add_parser('restore', help='Restore while the relay is stopped')
    restore.add_argument('snapshot')
    restore.add_argument('--data-dir', default=os.getenv('CRIER_DATA_DIR', 'data'))
    restore.add_argument('--overwrite', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'backup':
            print(create_backup(args.data_dir, args.backup_dir, args.retain))
        elif args.command == 'verify':
            verify_backup(args.snapshot)
            print('Snapshot verified')
        else:
            print(restore_backup(args.snapshot, args.data_dir, args.overwrite))
    except (ValueError, RuntimeError, OSError, sqlite3.Error, subprocess.SubprocessError):
        # No database contents, tokens, or subprocess output in operator logs.
        parser.exit(1, 'Relay backup operation failed; check snapshot, paths, permissions, and offline restore requirements.\n')


if __name__ == '__main__':
    main()

