"""Offline profile snapshots. Call only after disconnecting and closing workers.

locked_profile=True is reserved for the application already holding desktop.lock.
Checksums detect damage; they do not authenticate an attacker-controlled backup.
"""
from contextlib import closing, nullcontext
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
from uuid import uuid4

from .lock import single_process
from .relay_backup import BackupError, _safe_path, _private_directory, _digest, _sync_directory

MAX_FILES = 10000
MAX_BYTES = 4 * 1024 ** 3
MAX_MANIFEST = 4 * 1024 ** 2
MANIFEST = 'manifest.json'


def _name(name):
    parts = PurePosixPath(name).parts
    if (not isinstance(name, str) or not parts or name.startswith('/') or '\\' in name
            or any(ord(c) < 32 or c in '<>"|?*' for c in name)
            or any(p in ('.', '..') or ':' in p or p.endswith((' ', '.'))
                   or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', p)
                   for p in parts) or str(PurePosixPath(name)) != name):
        raise BackupError('Unsafe backup name')
    return name


def _files(root):
    result = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = _safe_path(Path(directory) / name)
            if not (path.is_dir() or stat.S_ISREG(path.stat().st_mode)):
                raise BackupError('Only regular profile files are supported')
        for name in files:
            path = Path(directory) / name
            result.append((_name(path.relative_to(root).as_posix()), path))
            if len(result) > MAX_FILES:
                raise BackupError('Too many profile files')
    if sum(p.stat().st_size for _, p in result) > MAX_BYTES:
        raise BackupError('Profile exceeds backup size limit')
    return result


def _publish(stage, target):
    # Both paths atomically publish an entire directory without replacement.
    if os.name == 'nt':
        stage.rename(target)
    else:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, 'renameat2', None)
        if rename is None:
            raise BackupError('Atomic no-replace directory publication unavailable')
        if rename(-100, os.fsencode(stage), -100, os.fsencode(target), 1):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(target))
    _sync_directory(target.parent)


def _discard(stage):
    def writable_retry(function, path, error):
        _safe_path(path).chmod(0o700)
        function(path)
    if stage.exists():
        _safe_path(stage)
        shutil.rmtree(stage, onerror=writable_retry)


def create_backup(profile: Path, backup_root: Path, *, locked_profile=False) -> Path:
    """Snapshot a closed worker profile; normally acquire its process lock."""
    profile = _safe_path(profile); backup_root = _safe_path(backup_root)
    if not profile.is_dir() or backup_root == profile or profile in backup_root.parents:
        raise BackupError('Backup root must be outside an existing profile')
    lock_path = _safe_path(profile / 'desktop.lock')
    with nullcontext() if locked_profile else single_process(lock_path):
        sources = [(name, path) for name, path in _files(profile) if name != 'desktop.lock']
        if any(name == MANIFEST for name, _ in sources):
            raise BackupError('Reserved manifest name in profile')
        _private_directory(backup_root)
        stage = backup_root / ('.pending-' + uuid4().hex)
        _private_directory(stage)
        target = backup_root / ('profile-' + uuid4().hex)
        try:
            entries = []
            sqlite_names = set()
            for name, source in sources:
                with source.open('rb') as handle: header = handle.read(16)
                if header == b'SQLite format 3\x00': sqlite_names.add(name)
            for name, source in sources:
                if name == 'desktop.lock' or any(name == base + suffix for base in sqlite_names for suffix in ('-wal', '-shm', '-journal')):
                    continue
                dest = stage / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if name in sqlite_names:
                    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(dest)) as out:
                        src.backup(out)
                        out.execute('PRAGMA journal_mode=DELETE')
                else:
                    shutil.copyfile(source, dest)
                dest.chmod(0o600)
                entries.append({'name': name, 'size': dest.stat().st_size, 'sha256': _digest(dest)})
            metadata = {'schema': 1, 'files': entries}
            (stage / MANIFEST).write_text(json.dumps(metadata, sort_keys=True), encoding='utf-8')
            (stage / MANIFEST).chmod(0o400)
            validate_backup(stage)
            _publish(stage, target)
            return target
        finally:
            _discard(stage)


def validate_backup(path: Path) -> dict:
    path = _safe_path(path)
    manifest = _safe_path(path / MANIFEST)
    if not manifest.is_file() or manifest.stat().st_size > MAX_MANIFEST:
        raise BackupError('Missing or oversized manifest')
    try: metadata = json.loads(manifest.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError): raise BackupError('Invalid manifest') from None
    if not isinstance(metadata, dict) or set(metadata) != {'schema', 'files'} or type(metadata['schema']) is not int or metadata['schema'] != 1:
        raise BackupError('Unsupported manifest schema')
    entries = metadata['files']
    if not isinstance(entries, list) or len(entries) > MAX_FILES:
        raise BackupError('Invalid file list')
    expected = {MANIFEST}; total = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'name', 'size', 'sha256'} or not isinstance(entry['name'], str):
            raise BackupError('Invalid file entry')
        name = _name(entry['name'])
        if name.casefold() in {n.casefold() for n in expected} or type(entry['size']) is not int or entry['size'] < 0 or not isinstance(entry['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', entry['sha256']):
            raise BackupError('Invalid or duplicate file entry')
        expected.add(name); total += entry['size']
        if total > MAX_BYTES: raise BackupError('Backup exceeds size limit')
        source = _safe_path(path / name)
        if not source.is_file() or source.stat().st_size != entry['size'] or _digest(source) != entry['sha256']:
            raise BackupError('Backup checksum mismatch')
    if {name for name, _ in _files(path)} != expected:
        raise BackupError('Unexpected backup files')
    return metadata


def restore_backup(backup: Path, destination: Path) -> Path:
    """Restore to an absent destination; never change an existing profile."""
    metadata = validate_backup(backup); backup = _safe_path(backup)
    destination = _safe_path(destination)
    if destination.exists(): raise BackupError('Restore destination already exists')
    _safe_path(destination.parent)
    stage = destination.parent / ('.restore-' + uuid4().hex)
    _private_directory(stage)
    try:
        for entry in metadata['files']:
            source = _safe_path(backup / entry['name']); target = stage / entry['name']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target); target.chmod(0o600)
            if _digest(target) != entry['sha256']: raise BackupError('Backup changed during restore')
        _publish(stage, destination)
        return destination
    finally:
        _discard(stage)


def ensure_profile_compatible(profile: Path, *, generation=1):
    """Check public profile generation; this does not migrate database schemas."""
    profile = _safe_path(profile); marker = _safe_path(profile / 'profile-format.json')
    if type(generation) is not int or generation != 1:
        raise BackupError('Unsupported application profile generation')
    if marker.exists():
        if marker.stat().st_size > 4096: raise BackupError('Invalid profile format marker')
        try: data = json.loads(marker.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError): raise BackupError('Invalid profile format marker') from None
        if data != {'schema': 1, 'generation': generation} or any(type(v) is not int for v in data.values()):
            raise BackupError('Unsupported profile generation')
        return data
    profile.mkdir(parents=True, exist_ok=True)
    data = {'schema': 1, 'generation': generation}
    temp = profile / ('.profile-format-' + uuid4().hex)
    try:
        with temp.open('x', encoding='utf-8') as handle:
            json.dump(data, handle); handle.flush(); os.fsync(handle.fileno())
        temp.chmod(0o600)
        # Hard link publishes without overwriting a concurrent marker.
        os.link(temp, marker)
    finally:
        temp.unlink(missing_ok=True)
    return data

