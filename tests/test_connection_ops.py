from collections import namedtuple
from contextlib import contextmanager
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from crier.config import Config
from crier.connection_server import create_connection_app
from crier.relay_ops import OpsSettings


OWNER = 'o' * 32
AUTH = {'Authorization': 'Bearer ' + OWNER}
Usage = namedtuple('Usage', 'total used free')


@pytest.fixture
def app(tmp_path):
    return create_connection_app(Config(data_dir=tmp_path, token=OWNER, public_pairing_enabled=True))

def test_public_probe_cached_and_never_waits_for_another_probe(app,monkeypatch):
    ops=app.state.relay_ops
    calls=[]
    monkeypatch.setattr(ops,'readiness',lambda: calls.append(True) or {'ready':True})
    assert ops.public_ready()
    assert ops.public_ready()
    assert len(calls)==1
    ops.public_probe=(0,True)
    with ops.probe_lock:
        assert ops.public_ready()
    assert len(calls)==1


def test_public_health_minimal_owner_status_private(app):
    channel = app.state.relay.create('private-account-name', 'paper')
    with TestClient(app) as client:
        health = client.get('/health')
        assert health.status_code == 200
        assert health.json() == {'status': 'ok', 'pairing_enabled': True, 'protocol': 1}
        for credential in (None, channel['host_token'], channel['follower_token']):
            headers = {} if credential is None else {'Authorization': 'Bearer ' + credential}
            assert client.get('/api/ops', headers=headers).status_code == 401
        status = client.get('/api/ops', headers=AUTH)
        assert status.status_code == 200
        body = status.json()
        assert body['counts'] == {'channels': 1, 'receivers': 0, 'events': 0}
        assert body['database'] == {'ready': True}
        assert body['disk']['ready']
        assert body['uptime_seconds'] >= 0
        for secret in (OWNER, channel['host_token'], channel['follower_token'], channel['id'], 'private-account-name'):
            assert secret not in status.text
        assert status.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('table', ['channels', 'receivers', 'intents', 'diagnostics', 'invitations', 'connection_limits'])
def test_health_requires_real_schema(app, table):
    with app.state.relay.db() as db:
        db.execute(f'DROP TABLE {table}')
    with TestClient(app) as client:
        response = client.get('/health')
        assert response.status_code == 503
        assert response.json()['status'] == 'unavailable'
        ops = client.get('/api/ops', headers=AUTH)
        assert ops.status_code == 503
        assert not ops.json()['database']['ready']
        assert 'counts' not in ops.json()
        assert table not in response.text


def test_health_detects_partial_schema(app):
    with app.state.relay.db() as db:
        db.execute('ALTER TABLE receivers RENAME COLUMN start_cursor TO missing_column')
    with TestClient(app) as client:
        assert client.get('/health').status_code == 503


def test_database_failure_is_graceful_and_does_not_leak(app, monkeypatch):
    @contextmanager
    def broken():
        raise sqlite3.OperationalError('secret-password /private/db.sqlite3')
        yield
    monkeypatch.setattr(app.state.relay, 'db', broken)
    with TestClient(app) as client:
        for path, headers in (('/health', {}), ('/api/ops', AUTH)):
            response = client.get(path, headers=headers)
            assert response.status_code == 503
            assert 'secret-password' not in response.text
            assert '/private' not in response.text
        assert client.get('/api/ops').status_code == 401


@pytest.mark.parametrize('usage,settings,ready', [
    (Usage(1000, 900, 100), OpsSettings(100, 10), True),
    (Usage(1000, 901, 99), OpsSettings(100, 0), False),
    (Usage(1000, 901, 99), OpsSettings(0, 10), False),
])
def test_disk_thresholds(app, monkeypatch, usage, settings, ready):
    monkeypatch.setattr('crier.relay_ops.shutil.disk_usage', lambda path: usage)
    app.state.relay_ops.settings = settings
    with TestClient(app) as client:
        assert client.get('/health').status_code == (200 if ready else 503)
        response = client.get('/api/ops', headers=AUTH)
        assert response.json()['disk']['ready'] is ready
        assert response.json()['disk']['free_bytes'] == usage.free


def test_unwritable_disk_is_unready(app, monkeypatch):
    def broken(**kwargs):
        raise OSError('secret disk path')
    monkeypatch.setattr('crier.relay_ops.tempfile.TemporaryFile', broken)
    with TestClient(app) as client:
        assert client.get('/health').status_code == 503
        response = client.get('/api/ops', headers=AUTH)
        assert response.status_code == 503
        assert response.json()['disk'] == {'ready': False}
        assert 'secret disk path' not in response.text


def test_metrics_redact_routes_and_measure_all_responses(app):
    with TestClient(app) as client:
        client.get('/health?token=private-query')
        client.get('/api/sync/channels')
        client.post('/api/sync/revoke/private-channel', headers=AUTH)
        for identity in ('private-token-one', 'private-token-two'):
            client.get('/' + identity + '?token=private-query')
        client.post('/api/connect/host', content=b'x' * 32769)
        metrics = client.get('/api/ops', headers=AUTH).json()['requests']
        encoded = json.dumps(metrics)
        for secret in ('private-query', 'private-channel', 'private-token-one', 'private-token-two'):
            assert secret not in encoded
        indexed = {(item['route'], item['method'], item['status']): item for item in metrics}
        assert indexed[('unmatched', 'GET', 404)]['count'] == 2
        assert indexed[('/api/sync/revoke/{identity}', 'POST', 200)]['count'] == 1
        assert indexed[('/api/sync/channels', 'GET', 401)]['count'] == 1
        assert indexed[('unmatched', 'POST', 413)]['count'] == 1
        assert all(item['latency_seconds_sum'] >= item['latency_seconds_max'] >= 0 for item in metrics)


def test_operations_threshold_settings_and_job_hooks(monkeypatch, app):
    monkeypatch.setenv('CRIER_RELAY_MIN_FREE_BYTES', '123')
    monkeypatch.setenv('CRIER_RELAY_MIN_FREE_PERCENT', '2.5')
    assert OpsSettings.from_env() == OpsSettings(123, 2.5)
    for settings in ((-1, 1), (1, -1), (1, 101), (1, float('nan'))):
        with pytest.raises(ValueError):
            OpsSettings(*settings)
    app.state.relay_ops.record_job('backup', True)
    assert app.state.relay_ops.snapshot()['jobs']['backup']['success']
    with pytest.raises(ValueError):
        app.state.relay_ops.record_job('private-channel', True)
