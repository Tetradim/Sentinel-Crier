from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from crier.intent_relay import IntentRelay, sync_router
from test_intent_relay import event


@pytest.fixture
def setup(tmp_path):
    relay = IntentRelay(tmp_path / 'relay.db')
    pair = relay.create('Diagnostics', 'paper')
    instruction = event()
    relay.publish(pair['host_token'], instruction)
    app = FastAPI()
    app.include_router(sync_router(relay, lambda: None))
    return relay, pair, instruction, TestClient(app)


def headers(token):
    return {'Authorization': 'Bearer ' + token}


def observation(stage='sender'):
    now = datetime.now(timezone.utc).isoformat()
    return dict(stage=stage, observed_at=now, clock_offset_ms=12,
                clock_uncertainty_ms=4, clock_sampled_at=now,
                quote=dict(source='alpaca:opra', quote_timestamp=now,
                           bid='0.19', ask='0.20', last=None), quote_error=None)


def test_clock_requires_current_channel_credentials(setup):
    relay, pair, _, client = setup
    assert client.get('/api/sync/clock').status_code == 401
    for role in ('host', 'follower'):
        response = client.get('/api/sync/clock', headers=headers(pair[role + '_token']))
        assert response.status_code == 200
        assert abs(response.json()['server_time_ms'] - datetime.now(timezone.utc).timestamp()*1000) < 2000
    relay.revoke(pair['id'])
    assert client.get('/api/sync/clock', headers=headers(pair['host_token'])).status_code == 401


def test_observation_is_scoped_idempotent_and_role_checked(setup):
    relay, pair, instruction, client = setup
    body = dict(event_id=instruction.event_id, observation=observation())
    url = '/api/sync/diagnostics'
    assert client.post(url, json=body, headers=headers(pair['follower_token'])).status_code == 403
    for _ in range(2):
        assert client.post(url, json=body, headers=headers(pair['host_token'])).status_code == 200
    receiver_body = dict(event_id=instruction.event_id, observation=observation('receiver'))
    assert client.post(url, json=receiver_body, headers=headers(pair['follower_token'])).status_code == 200
    response = client.get(url, params={'event_id': instruction.event_id}, headers=headers(pair['follower_token']))
    assert {r['observation']['stage'] for r in response.json()['observations']} == {'sender', 'receiver'}
    assert len(client.get(url, params={'event_id': instruction.event_id}, headers=headers(pair['host_token'])).json()['observations']) == 1
    other = relay.create('Other', 'paper')
    assert client.get(url, params={'event_id': instruction.event_id}, headers=headers(other['host_token'])).status_code == 404
    body['observation']['clock_offset_ms'] = 99
    assert client.post(url, json=body, headers=headers(pair['host_token'])).status_code == 409


@pytest.mark.parametrize('field,value', [('clock_offset_ms', float('inf')), ('clock_uncertainty_ms', -1),
                                      ('observed_at', '2026-10-21T10:00:00'), ('stage', 'broker')])
def test_invalid_diagnostics_rejected(setup, field, value):
    _, pair, instruction, client = setup
    import json
    obs = observation()
    obs[field] = value
    response = client.post('/api/sync/diagnostics', content=json.dumps(dict(event_id=instruction.event_id, observation=obs)),
                           headers=dict(headers(pair['host_token']), **{'Content-Type':'application/json'}))
    assert response.status_code == 422


def test_quote_validation_and_missing_event(setup):
    _, pair, instruction, client = setup
    body = dict(event_id=event().event_id, observation=observation())
    assert client.post('/api/sync/diagnostics', json=body, headers=headers(pair['host_token'])).status_code == 404
    body['event_id'] = instruction.event_id
    body['observation']['quote']['ask'] = 'NaN'
    assert client.post('/api/sync/diagnostics', json=body, headers=headers(pair['host_token'])).status_code == 422


def test_receivers_cannot_read_each_other_or_pre_join_events(setup):
    from hashlib import sha256
    relay, pair, instruction, client = setup
    with relay.db() as db:
        for name, cursor in [('one', 0), ('two', 0), ('late', 999)]:
            db.execute('INSERT INTO receivers VALUES (?,?,?,?,0,?)',
                       (name, pair['id'], sha256(name.encode()).hexdigest(), 0, cursor))
    url = '/api/sync/diagnostics'
    for name in ('one', 'two'):
        body = dict(event_id=instruction.event_id, observation=observation('receiver'))
        assert client.post(url, json=body, headers=headers(name)).status_code == 200
        rows = client.get(url, params={'event_id': instruction.event_id}, headers=headers(name)).json()['observations']
        assert [r['actor'] for r in rows] == [name]
    assert client.get(url, params={'event_id': instruction.event_id}, headers=headers('late')).status_code == 404
    assert client.post(url, json=body, headers=headers('late')).status_code == 404
    with relay.db() as db:
        db.execute("UPDATE receivers SET revoked=1 WHERE id='one'")
    assert client.get(url, params={'event_id': instruction.event_id}, headers=headers('one')).status_code == 401
