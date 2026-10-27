"""Authenticated, bounded Windows update staging. This module never executes files."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import threading
import socket
from contextlib import contextmanager, ExitStack

from .relay_backup import _private_directory
from urllib.parse import urlsplit

import httpx
from httpcore._backends.sync import SyncStream
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


_DNS_SLOTS = threading.BoundedSemaphore(2)


class UpdateError(ValueError):
    """An update could not be safely authenticated or staged."""


class _NoRelease(Exception):
    pass


def _reject():
    raise UpdateError('Update verification failed')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _json(raw):
    return json.loads(raw, object_pairs_hook=_object, parse_constant=lambda _: _reject())


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value) or len(value) > 40:
        _reject()
    return tuple(map(int, value.split('.')))


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        _reject()


def _reparse(path):
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


class _DeadlineIO:
    """Cap httpcore socket operations, including response header reads."""
    def __init__(self, delegate, deadline, cancelled=None):
        self.delegate = delegate
        self.deadline = deadline
        self.cancelled = cancelled

    def _remaining(self, timeout):
        if self.cancelled is not None and self.cancelled.is_set():
            _reject()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            _reject()
        return min(15, remaining) if timeout is None else min(15, timeout, remaining)

    def read(self, max_bytes, timeout=None):
        return self.delegate.read(max_bytes, timeout=self._remaining(timeout))

    def write(self, buffer, timeout=None):
        return self.delegate.write(buffer, timeout=self._remaining(timeout))

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return _DeadlineIO(self.delegate.start_tls(ssl_context, server_hostname=server_hostname, timeout=self._remaining(timeout)), self.deadline, self.cancelled)

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        # DNS cannot be interrupted portably. Bound its callers and retain no
        # more than two abandoned daemon resolvers if the OS resolver stalls.
        slots = _DNS_SLOTS
        while not slots.acquire(timeout=min(0.1, self._remaining(timeout))):
            self._remaining(timeout)
        completed = threading.Event()
        answer = []
        def resolve():
            try:
                answer.append(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except Exception as error:
                answer.append(error)
            finally:
                slots.release()
                completed.set()
        try:
            threading.Thread(target=resolve, name='update-dns', daemon=True).start()
        except Exception:
            slots.release()
            raise
        while not completed.wait(min(0.1, self._remaining(timeout))):
            self._remaining(timeout)
        self._remaining(timeout)
        if isinstance(answer[0], Exception):
            raise answer[0]
        last_error = OSError('No update host addresses')
        for family, kind, protocol, _, address in answer[0]:
            self._remaining(timeout)
            connection = socket.socket(family, kind, protocol)
            try:
                for option in socket_options or ():
                    connection.setsockopt(*option)
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                if local_address is not None:
                    connection.bind((local_address, 0))
                connection.settimeout(self._remaining(timeout))
                connection.connect(address)
                self._remaining(timeout)
                return _DeadlineIO(SyncStream(connection), self.deadline, self.cancelled)
            except Exception as error:
                connection.close()
                last_error = error
        raise last_error

    def __getattr__(self, name):
        return getattr(self.delegate, name)


@contextmanager
def _guard_path(path, directory=False, create=False):
    """Pin Windows objects against rename/delete, and reject reparse handles."""
    if os.name != 'nt':
        if _reparse(path):
            _reject()
        if directory:
            yield None
        else:
            flags = os.O_RDONLY if not create else os.O_RDWR | os.O_CREAT | os.O_EXCL
            fd = os.open(path, flags | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'r+b' if create else 'rb') as stream:
                yield stream
        return
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    open_file = kernel.CreateFileW
    open_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    open_file.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    access = 0 if directory else (0xC0000000 if create else 0x80000000)
    share = 3 if directory else (0 if create else 1)
    handle = open_file(str(path), access, share, None, 1 if create else 3,
                       0x00200000 | (0x02000000 if directory else 0), None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    owned = True
    try:
        info = (wintypes.DWORD * 2)()
        query = kernel.GetFileInformationByHandleEx
        query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        query.restype = wintypes.BOOL
        if not query(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or info[0] & 0x400:
            _reject()
        if directory:
            yield None
        else:
            fd = msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_RDWR if create else os.O_RDONLY))
            owned = False
            with os.fdopen(fd, 'r+b' if create else 'rb') as stream:
                yield stream
    finally:
        if owned:
            close(handle)


@contextmanager
def _guard_ancestors(path):
    with ExitStack() as stack:
        for ancestor in reversed((path, *path.parents)):
            stack.enter_context(_guard_path(ancestor, directory=True))
        yield


class UpdateClient:
    def __init__(self, policy, current_version, staging_root=None, profile_generation=1, protocol_generation=1, client=None):
        self.policy = dict(policy)
        self.current_version = current_version
        self.staging_root = Path(staging_root) if staging_root is not None else None
        self.profile_generation = profile_generation
        self.protocol_generation = protocol_generation
        self.client = client
        self._cancelled = threading.Event()
        self._metadata = None
        self._staged = None

    def cancel(self):
        """Cooperatively stop ongoing requests; blocked socket reads last at most 15s."""
        self._cancelled.set()

    def _ensure_active(self):
        if self._cancelled.is_set():
            _reject()

    @property
    def release(self):
        """A detached copy of authenticated available-release metadata."""
        if self._metadata is None:
            _reject()
        return copy.deepcopy(self._metadata)

    def _fetch(self, url, limit, sink=None):
        self._ensure_active()
        deadline = time.monotonic() + (600 if sink is not None else 30)
        if self.client is None:
            transport = httpx.HTTPTransport(trust_env=False, retries=0)
            # HTTPX 0.28.1 is pinned by this application. Its pool backend is
            # wrapped so trickled HTTP headers share the same total deadline.
            pool = getattr(transport, '_pool', None)
            backend = getattr(pool, '_network_backend', None)
            if backend is None or not callable(getattr(backend, 'connect_tcp', None)):
                if callable(getattr(transport, 'close', None)):
                    transport.close()
                _reject()
            pool._network_backend = _DeadlineIO(backend, deadline, self._cancelled)
            client = httpx.Client(transport=transport, trust_env=False, follow_redirects=False)
        else:
            client = self.client
        try:
            for redirects in range(4):
                self._ensure_active()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _reject()
                accept='application/vnd.github+json' if urlsplit(url).netloc=='api.github.com' else 'application/octet-stream'
                with client.stream('GET', url, follow_redirects=False, timeout=httpx.Timeout(min(15, remaining), connect=min(5, remaining)), headers={'Accept':accept, 'Accept-Encoding':'identity'}) as response:
                    self._ensure_active()
                    if time.monotonic() >= deadline:
                        _reject()
                    if redirects == 0 and url == 'https://api.github.com/repos/Tetradim/Sentinel-Crier/releases/latest' and response.status_code == 404:
                        raise _NoRelease()
                    if response.status_code in (301, 302, 303, 307, 308):
                        target = response.headers.get('location', '')
                        parsed = urlsplit(target)
                        if redirects == 3 or parsed.scheme != 'https' or parsed.netloc != 'release-assets.githubusercontent.com' or parsed.username or parsed.password or parsed.fragment:
                            _reject()
                        url = target
                        continue
                    if response.status_code != 200 or response.headers.get('content-encoding', 'identity') != 'identity':
                        _reject()
                    total = 0
                    chunks = []
                    network = response.extensions.get('network_stream')
                    original_read = getattr(network, 'read', None)
                    if original_read is not None:
                        def bounded_read(max_bytes, timeout=None):
                            self._ensure_active()
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                _reject()
                            return original_read(max_bytes, timeout=min(15, remaining))
                        network.read = bounded_read
                    # Preloaded MockTransport responses have already consumed their raw stream.
                    iterator = iter((response.content,)) if response.is_stream_consumed else response.iter_raw(chunk_size=None)
                    try:
                        for chunk in iterator:
                            self._ensure_active()
                            if time.monotonic() >= deadline:
                                _reject()
                            total += len(chunk)
                            if total > limit:
                                _reject()
                            if sink is not None:
                                sink.write(chunk)
                            else:
                                chunks.append(chunk)
                    finally:
                        if original_read is not None:
                            network.read = original_read
                    self._ensure_active()
                    if time.monotonic() >= deadline:
                        _reject()
                    return total if sink is not None else b''.join(chunks)
            _reject()
        finally:
            if self.client is None:
                client.close()

    def check(self):
        self._cancelled.clear()
        self._metadata = None
        self._staged = None
        if self.policy.get('enabled') is not True or not self.policy.get('public_keys'):
            return {'status':'unconfigured'}
        try:
            if self.policy.get('schema') != 1 or self.policy.get('repository') != 'Tetradim/Sentinel-Crier' or self.policy.get('channel') != 'stable':
                _reject()
            release = _json(self._fetch('https://api.github.com/repos/Tetradim/Sentinel-Crier/releases/latest', 262144))
            if release.get('draft') is not False or release.get('prerelease') is not False:
                _reject()
            tag = release['tag_name']
            _version(tag[1:] if isinstance(tag, str) and tag.startswith('v') else '')
            base = 'https://github.com/Tetradim/Sentinel-Crier/releases/download/' + tag + '/'
            assets = [a for a in release['assets'] if a.get('name') == 'SentinelCrier-update.json']
            if len(assets) != 1 or assets[0].get('browser_download_url') != base+'SentinelCrier-update.json':
                _reject()
            envelope = _json(self._fetch(base+'SentinelCrier-update.json', 32768))
            _keys(envelope, 'schema key_id payload signature')
            if type(envelope['schema']) is not int or envelope['schema'] != 1:
                _reject()
            public = base64.b64decode(self.policy['public_keys'][envelope['key_id']], validate=True)
            raw = base64.b64decode(envelope['payload'], validate=True)
            signature = base64.b64decode(envelope['signature'], validate=True)
            Ed25519PublicKey.from_public_bytes(public).verify(signature, raw)
            payload = _json(raw)
            _keys(payload, 'schema version platform source_commit release_tag installer compatibility notes')
            version = _version(payload['version'])
            if type(payload['schema']) is not int or payload['schema'] != 1 or payload['platform'] != 'windows-x64' or not re.fullmatch('[0-9a-f]{40}', payload['source_commit']):
                _reject()
            if payload['release_tag'] != tag or tag != 'v'+payload['version']:
                _reject()
            installer = payload['installer']
            _keys(installer, 'name url bytes sha256')
            name = 'SentinelCrier-'+payload['version']+'-Windows-Setup.exe'
            if installer['name'] != name or installer['url'] != base+name or type(installer['bytes']) is not int or not 0 < installer['bytes'] <= 512*1024*1024 or not re.fullmatch('[0-9a-f]{64}', installer['sha256']):
                _reject()
            compat = payload['compatibility']
            _keys(compat, 'min_source_version max_source_version profile_generation protocol_generation')
            current = _version(self.current_version)
            minimum = _version(compat['min_source_version'])
            maximum = _version(compat['max_source_version'])
            if minimum > maximum or (version > current and not minimum <= current <= maximum):
                _reject()
            if type(compat['profile_generation']) is not int or type(compat['protocol_generation']) is not int or compat['profile_generation'] != self.profile_generation or compat['protocol_generation'] != self.protocol_generation or version < current:
                _reject()
            if not isinstance(payload['notes'], str) or len(payload['notes']) > 4000:
                _reject()
            self._ensure_active()
            if version > current:
                self._metadata = payload
            return {'status':'available' if version > current else 'up_to_date', 'version':payload['version'], 'notes':payload['notes']}
        except _NoRelease:
            return {'status': 'no_release'}
        except Exception:
            raise UpdateError('Update verification failed') from None

    def _safe_root(self):
        if self.staging_root is None:
            _reject()
        root = self.staging_root.absolute()
        for path in (root, *root.parents):
            if _reparse(path):
                _reject()
        existing = root
        missing = []
        while not existing.exists():
            missing.append(existing)
            existing = existing.parent
        with _guard_ancestors(existing), ExitStack() as stack:
            for directory in reversed(missing):
                directory.mkdir(mode=0o700, exist_ok=True)
                stack.enter_context(_guard_path(directory, directory=True))
            return _private_directory(root)

    def download(self):
        directory = None
        target = None
        created_identity = None
        self._staged = None
        try:
            self._ensure_active()
            if self._metadata is None:
                _reject()
            root = self._safe_root()
            with _guard_ancestors(root):
                directory = Path(tempfile.mkdtemp(prefix='update-', dir=root))
                with _guard_path(directory, directory=True):
                    _private_directory(directory)
                    target = directory / self._metadata['installer']['name']
                    # CREATE_NEW/O_EXCL publishes a fresh object; never overwrite another file.
                    with _guard_path(target, create=True) as stream:
                        created = os.fstat(stream.fileno())
                        created_identity = (created.st_dev, created.st_ino)
                        self._fetch(self._metadata['installer']['url'], self._metadata['installer']['bytes'], stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                        self._validate_stream(stream)
                    self._ensure_active()
                    self._staged = target
                    return self.verify_staged()
        except Exception:
            self._staged = None
            # Do not follow changed ancestors during cleanup.
            if directory is not None:
                try:
                    with _guard_ancestors(directory):
                        if target is not None and created_identity is not None:
                            actual = target.stat(follow_symlinks=False)
                            if (actual.st_dev, actual.st_ino) == created_identity:
                                target.unlink()
                        directory.rmdir()
                except OSError:
                    pass
            raise UpdateError('Update staging failed') from None

    def _validate_stream(self, stream):
        stream.seek(0)
        digest = hashlib.sha256()
        total = 0
        for chunk in iter(lambda: stream.read(65536), b''):
            self._ensure_active()
            total += len(chunk)
            if total > self._metadata['installer']['bytes']:
                _reject()
            digest.update(chunk)
        if total != self._metadata['installer']['bytes'] or digest.hexdigest() != self._metadata['installer']['sha256']:
            _reject()

    def verify_staged(self):
        try:
            if self._metadata is None or self._staged is None or self._staged.parent.parent != self._safe_root():
                _reject()
            with _guard_ancestors(self._staged.parent):
                with _guard_path(self._staged) as stream:
                    before = os.fstat(stream.fileno())
                    self._validate_stream(stream)
                    after = self._staged.stat(follow_symlinks=False)
                    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                        _reject()
            return self._staged
        except Exception:
            raise UpdateError('Staged update verification failed') from None
