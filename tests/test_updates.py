import base64
import hashlib
import json

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from crier.updates import UpdateClient, UpdateError


def fixture_client(tmp_path, mutate=None, body=b'installer', redirect=None):
    key = Ed25519PrivateKey.generate()
    version = '0.3.0'
    name = f'SentinelCrier-{version}-Windows-Setup.exe'
    base = f'https://github.com/Tetradim/Sentinel-Crier/releases/download/v{version}/'
    payload = dict(schema=1, version=version, platform='windows-x64', source_commit='a'*40,
                   release_tag='v'+version, installer=dict(name=name, url=base+name, bytes=len(body), sha256=hashlib.sha256(body).hexdigest()),
                   compatibility=dict(min_source_version='0.1.0', max_source_version='0.3.0', profile_generation=1, protocol_generation=1), notes='Release notes')
    if mutate:
        mutate(payload)
    raw = json.dumps(payload).encode()
    envelope = dict(schema=1, key_id='test', payload=base64.b64encode(raw).decode(), signature=base64.b64encode(key.sign(raw)).decode())
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if request.url.host == 'api.github.com':
            return httpx.Response(200, json=dict(tag_name='v'+version, draft=False, prerelease=False, assets=[dict(name='SentinelCrier-update.json', browser_download_url=base+'SentinelCrier-update.json')]))
        if request.url.path.endswith('.json'):
            return httpx.Response(200, json=envelope)
        if redirect:
            return httpx.Response(302, headers={'location': redirect})
        return httpx.Response(200, content=body)
    policy = dict(schema=1, repository='Tetradim/Sentinel-Crier', channel='stable', enabled=True, public_keys={'test':base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()})
    return UpdateClient(policy, '0.2.0', staging_root=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler))), envelope, calls


def test_signed_update_download_rechecks_staged_bytes(tmp_path):
    client, _, calls = fixture_client(tmp_path)
    assert client.check() == dict(status='available', version='0.3.0', notes='Release notes')
    path = client.download()
    assert path.read_bytes() == b'installer'
    assert client.verify_staged() == path
    path.write_bytes(b'tampered')
    with pytest.raises(UpdateError):
        client.verify_staged()
    assert len(calls) == 3


def test_disabled_never_connects(tmp_path):
    client = UpdateClient({}, '0.2.0', staging_root=tmp_path)
    assert client.check() == {'status':'unconfigured'}


def test_release_metadata_uses_github_json_media_type(tmp_path):
    client, _, _ = fixture_client(tmp_path)
    def respond(request):
        # Matches GitHub's real 415 for octet-stream on release metadata.
        status=404 if request.headers['accept']=='application/vnd.github+json' else 415
        return httpx.Response(status)
    client.client=httpx.Client(transport=httpx.MockTransport(respond))
    assert client.check()=={'status':'no_release'}


def test_missing_latest_release_is_safe_empty_state(tmp_path):
    client, _, _ = fixture_client(tmp_path)
    client.check()
    client.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    assert client.check() == {'status': 'no_release'}
    with pytest.raises(UpdateError):
        _ = client.release


def test_manifest_404_remains_verification_failure(tmp_path):
    client, _, _ = fixture_client(tmp_path)
    original = client.client
    def handler(request):
        if request.url.path.endswith('.json'):
            return httpx.Response(404)
        return original.send(request)
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(UpdateError):
        client.check()


def test_release_is_authenticated_and_cannot_mutate_cache(tmp_path):
    client, _, _ = fixture_client(tmp_path)
    with pytest.raises(UpdateError):
        _ = client.release
    client.check()
    release = client.release
    release['installer']['sha256'] = '0'*64
    assert client.release['installer']['sha256'] != '0'*64


def test_current_release_is_up_to_date_outside_upgrade_source_range(tmp_path):
    def mutation(payload):
        payload['compatibility'].update(min_source_version='0.2.0', max_source_version='0.2.0')
    client, _, _ = fixture_client(tmp_path, mutation)
    client.current_version = '0.3.0'
    assert client.check() == {'status': 'up_to_date', 'version': '0.3.0', 'notes': 'Release notes'}
    with pytest.raises(UpdateError):
        _ = client.release


def test_reversed_source_range_refused_even_if_current_release(tmp_path):
    def mutation(payload):
        payload['compatibility'].update(min_source_version='0.3.0', max_source_version='0.2.0')
    client, _, _ = fixture_client(tmp_path, mutation)
    client.current_version = '0.3.0'
    with pytest.raises(UpdateError):
        client.check()


@pytest.mark.parametrize('mutate', [
    lambda p: p.update(version='0.1.0'),
    lambda p: p.update(platform='linux'),
    lambda p: p['installer'].update(url='https://github.com/evil/repo/file'),
    lambda p: p['installer'].update(name='../evil.exe'),
    lambda p: p['compatibility'].update(profile_generation=2),
    lambda p: p['compatibility'].update(min_source_version='0.3.0'),
    lambda p: p['installer'].update(bytes=536870913),
])
def test_authenticated_but_invalid_metadata_rejected(tmp_path, mutate):
    client, _, _ = fixture_client(tmp_path, mutate)
    with pytest.raises(UpdateError):
        client.check()


def test_signature_tampering_rejected(tmp_path):
    client, envelope, _ = fixture_client(tmp_path)
    envelope['payload'] = base64.b64encode(b'{}').decode()
    with pytest.raises(UpdateError):
        client.check()


@pytest.mark.parametrize('url', ['http://release-assets.githubusercontent.com/file', 'https://evil.test/file', 'https://github.com/evil/file', 'https://user@release-assets.githubusercontent.com/file'])
def test_download_redirect_allowlist(tmp_path, url):
    client, _, _ = fixture_client(tmp_path, redirect=url)
    client.check()
    with pytest.raises(UpdateError):
        client.download()


@pytest.mark.parametrize('mutation', [
    lambda p: p['installer'].update(sha256='0'*64),
    lambda p: p['installer'].update(bytes=1),
    lambda p: p['installer'].update(bytes=100),
])
def test_download_rejects_hash_and_size_mismatch(tmp_path, mutation):
    client, _, _ = fixture_client(tmp_path, mutation)
    client.check()
    with pytest.raises(UpdateError):
        client.download()
    assert list(tmp_path.iterdir()) == []


def test_duplicate_envelope_keys_rejected(tmp_path):
    client, _, _ = fixture_client(tmp_path)
    original = client.client
    def handler(request):
        if request.url.path.endswith('.json'):
            return httpx.Response(200, content=b'{"schema":1,"schema":1}')
        return original.send(request)
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(UpdateError):
        client.check()


def test_recheck_failure_clears_authenticated_cache(tmp_path):
    client, envelope, _ = fixture_client(tmp_path)
    client.check()
    envelope['signature'] = 'invalid'
    with pytest.raises(UpdateError):
        client.check()
    with pytest.raises(UpdateError):
        client.download()


def test_preexisting_installer_refused(tmp_path):
    client, _, _ = fixture_client(tmp_path)
    client.check()
    existing = tmp_path / 'SentinelCrier-0.3.0-Windows-Setup.exe'
    existing.write_bytes(b'untrusted')
    assert client.download().parent != tmp_path
    assert existing.read_bytes() == b'untrusted'


def test_total_deadline_observes_small_raw_chunks(tmp_path, monkeypatch):
    from crier import updates
    clock = [0.0]
    monkeypatch.setattr(updates.time, 'monotonic', lambda: clock[0])
    class Trickle(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(5):
                clock[0] += 6
                yield b'x'
    client, _, _ = fixture_client(tmp_path)
    client.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Trickle())))
    with pytest.raises(UpdateError):
        client._fetch('https://github.com/test', 100)


def test_deadline_survives_redirects_and_limits_network_reads(tmp_path, monkeypatch):
    from crier import updates
    clock = [0.0]
    monkeypatch.setattr(updates.time, 'monotonic', lambda: clock[0])
    timeouts = []
    class Network:
        def read(self, max_bytes, timeout=None):
            timeouts.append(timeout)
            clock[0] += 10
            return b'x'
    network = Network()
    class Body(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(4):
                yield network.read(1, timeout=30)
    def handler(request):
        if request.url.host == 'github.com':
            clock[0] += 10
            return httpx.Response(302, headers={'location':'https://release-assets.githubusercontent.com/file'})
        return httpx.Response(200, stream=Body(), extensions={'network_stream':network})
    client, _, _ = fixture_client(tmp_path)
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(UpdateError):
        client._fetch('https://github.com/test', 100)
    assert timeouts == [15, 10]


def test_socket_backend_caps_connect_tls_and_header_reads(monkeypatch):
    from crier import updates
    clock = [0]
    monkeypatch.setattr(updates.time, 'monotonic', lambda: clock[0])
    observed = []
    class Socket:
        def connect_tcp(self, host, port, timeout=None, **kwargs):
            observed.append(timeout)
            clock[0] += 10
            return self
        def start_tls(self, context, server_hostname=None, timeout=None):
            observed.append(timeout)
            clock[0] += 10
            return self
        def read(self, count, timeout=None):
            observed.append(timeout)
            clock[0] += 10
            return b'header'
    backend = updates._DeadlineIO(Socket(), 30)
    clock[0] = 10
    connection = backend
    secure = connection.start_tls(None, timeout=100)
    assert secure.read(100, timeout=100) == b'header'
    with pytest.raises(UpdateError):
        secure.read(100)
    assert observed == [15, 10]


def test_cancelled_download_cleans_partial_artifact(tmp_path):
    client, _, _ = fixture_client(tmp_path)
    client.check()
    class CancelBody(httpx.SyncByteStream):
        def __iter__(self):
            yield b'ins'
            client.cancel()
            yield b'taller'
    client.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=CancelBody())))
    with pytest.raises(UpdateError):
        client.download()
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(UpdateError):
        client.download()


def test_metadata_and_installer_have_distinct_total_budgets(tmp_path, monkeypatch):
    from crier import updates
    clock = [0]
    monkeypatch.setattr(updates.time, 'monotonic', lambda: clock[0])
    class SlowBody(httpx.SyncByteStream):
        def __iter__(self):
            clock[0] += 40
            yield b'installer'
    client, _, _ = fixture_client(tmp_path)
    client.check()
    client.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=SlowBody())))
    with pytest.raises(UpdateError):
        client._fetch('https://github.com/test', 100)
    assert client.download().read_bytes() == b'installer'


def test_explicit_new_check_resets_cancellation(tmp_path):
    client, _, _ = fixture_client(tmp_path)
    client.cancel()
    assert client.check()['status'] == 'available'
    assert client.download().read_bytes() == b'installer'


def test_blocked_dns_is_cancellable_and_resolver_threads_are_bounded(monkeypatch):
    from crier import updates
    import threading
    import time
    entered = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    calls = []
    def stalled(*args, **kwargs):
        calls.append(True)
        entered.set()
        release.wait(5)
        return []
    monkeypatch.setattr(updates.socket, 'getaddrinfo', stalled)
    monkeypatch.setattr(updates, '_DNS_SLOTS', threading.BoundedSemaphore(1))
    network = updates._DeadlineIO(object(), time.monotonic()+5, cancelled)
    failures = []
    def connect():
        try:
            network.connect_tcp('example.test', 443)
        except UpdateError:
            failures.append(True)
    caller = threading.Thread(target=connect)
    caller.start()
    assert entered.wait(1)
    cancelled.set()
    caller.join(1)
    assert not caller.is_alive()
    assert failures == [True]
    for _ in range(3):
        with pytest.raises(UpdateError):
            network.connect_tcp('example.test', 443)
    assert len(calls) == 1
    release.set()


def test_each_resolved_address_receives_remaining_connect_budget(monkeypatch):
    from crier import updates
    clock = [0]
    monkeypatch.setattr(updates.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(updates.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('1.1.1.1',443)), (2,1,6,'',('2.2.2.2',443))])
    observed = []
    closed = []
    class FakeSocket:
        def settimeout(self, value):
            observed.append(value)
        def setsockopt(self, *args):
            pass
        def connect(self, address):
            clock[0] += 10
            raise OSError('synthetic failure')
        def close(self):
            closed.append(True)
    monkeypatch.setattr(updates.socket, 'socket', lambda *a: FakeSocket())
    with pytest.raises(OSError):
        updates._DeadlineIO(object(), 18).connect_tcp('example.test',443)
    assert observed == [15,8]
    assert closed == [True,True]


def test_production_transport_installs_deadline_backend_without_network(monkeypatch):
    from crier import updates
    real_transport = httpx.HTTPTransport
    transports = []
    def capture(**kwargs):
        value = real_transport(**kwargs)
        transports.append(value)
        return value
    monkeypatch.setattr(updates.httpx, 'HTTPTransport', capture)
    def stop_before_network(self, *args, **kwargs):
        assert isinstance(transports[0]._pool._network_backend, updates._DeadlineIO)
        raise UpdateError('synthetic stop')
    monkeypatch.setattr(updates.httpx.Client, 'stream', stop_before_network)
    with pytest.raises(UpdateError):
        UpdateClient({}, '0.2.0')._fetch('https://github.com/test', 100)


def test_unknown_httpx_backend_fails_closed(monkeypatch):
    from crier import updates
    monkeypatch.setattr(updates.httpx, 'HTTPTransport', lambda **_: object())
    with pytest.raises(UpdateError):
        UpdateClient({}, '0.2.0')._fetch('https://github.com/test', 100)


def test_ancestor_junction_swap_before_create_is_refused(tmp_path, monkeypatch):
    import os
    if os.name != 'nt':
        pytest.skip('Windows junction regression')
    import _winapi
    root = tmp_path / 'stage'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    client, _, _ = fixture_client(root)
    client.check()
    original = client._safe_root
    def raced_root():
        path = original()
        path.rename(tmp_path / 'moved')
        _winapi.CreateJunction(str(outside), str(path))
        return path
    monkeypatch.setattr(client, '_safe_root', raced_root)
    try:
        with pytest.raises(UpdateError):
            client.download()
        assert list(outside.iterdir()) == []
    finally:
        os.rmdir(root)


def test_new_stage_directory_is_private(tmp_path, monkeypatch):
    from crier import updates
    private = []
    original = updates._private_directory
    def provision(path):
        private.append(path)
        return original(path)
    monkeypatch.setattr(updates, '_private_directory', provision)
    client, _, _ = fixture_client(tmp_path)
    client.check()
    path = client.download()
    assert path.parent in private
    assert tmp_path in private


def test_raced_target_is_never_clobbered_or_removed(tmp_path, monkeypatch):
    from crier import updates
    from contextlib import contextmanager
    original = updates._guard_path
    raced = []
    @contextmanager
    def race(path, directory=False, create=False):
        if create:
            path.write_bytes(b'other owner')
            raced.append(path)
        with original(path, directory=directory, create=create) as stream:
            yield stream
    monkeypatch.setattr(updates, '_guard_path', race)
    client, _, _ = fixture_client(tmp_path)
    client.check()
    with pytest.raises(UpdateError):
        client.download()
    assert raced[0].read_bytes() == b'other owner'


def test_windows_streaming_handle_blocks_replace_and_ancestor_rename(tmp_path, monkeypatch):
    import os
    if os.name != 'nt':
        pytest.skip('Windows sharing regression')
    client, _, _ = fixture_client(tmp_path)
    client.check()
    original = client._fetch
    blocked = []
    def fetch(url, limit, sink=None):
        if sink is not None:
            directory = next(tmp_path.iterdir())
            target = directory / 'SentinelCrier-0.3.0-Windows-Setup.exe'
            for action in (lambda: target.write_bytes(b'attack'), lambda: directory.rename(tmp_path / 'moved')):
                with pytest.raises(OSError):
                    action()
                blocked.append(True)
        return original(url, limit, sink)
    monkeypatch.setattr(client, '_fetch', fetch)
    assert client.download().read_bytes() == b'installer'
    assert blocked == [True, True]


def test_root_reparse_points_rejected(tmp_path, monkeypatch):
    from crier import updates
    client, _, _ = fixture_client(tmp_path)
    client.check()
    original = updates.Path.lstat
    def fake_lstat(path):
        value = original(path)
        if path == tmp_path:
            class Reparse:
                st_file_attributes = 0x400
                st_mode = value.st_mode
            return Reparse()
        return value
    monkeypatch.setattr(updates.Path, 'lstat', fake_lstat)
    with pytest.raises(UpdateError):
        client.download()
