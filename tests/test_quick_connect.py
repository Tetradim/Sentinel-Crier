import time
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from crier.intent_relay import IntentRelay, sync_router
from crier.quick_connect import ConnectionService, connection_router
from test_intent_relay import event

def service(tmp_path):
    return ConnectionService(IntentRelay(tmp_path/'relay.sqlite3'))

def test_single_use_invite_gives_independent_read_only_credentials(tmp_path):
    s=service(tmp_path)
    host=s.create('iPhone','paper')
    invitation=s.invite(host['token'])
    follower=s.receive(invitation['code'])
    with pytest.raises(PermissionError): s.receive(invitation['code'])
    second=s.receive(s.invite(host['token'])['code'])
    assert follower['token'] != second['token']
    e=event(); s.relay.publish(host['token'], e)
    assert s.relay.read(follower['token'], 0)['events'][0]['event']==e.to_dict()
    with pytest.raises(PermissionError): s.relay.publish(follower['token'], e)
    with pytest.raises(PermissionError): s.invite(follower['token'])
    s.revoke_receiver(host['token'], s.receivers(host['token'])[0]['id'])
    with pytest.raises(PermissionError): s.relay.read(follower['token'],0)
    assert s.relay.read(second['token'],0)['events']

def test_expired_invite_and_revoked_channel_fail(tmp_path):
    s=service(tmp_path); host=s.create('Host','paper')
    invite=s.invite(host['token'], now=100)
    with pytest.raises(PermissionError): s.receive(invite['code'], now=701)
    fresh=s.invite(host['token'])
    s.relay.revoke(s.relay.channels()[0]['id'])
    with pytest.raises(PermissionError): s.receive(fresh['code'])

def test_wrong_environment_does_not_consume_invitation(tmp_path):
    s=service(tmp_path); host=s.create('Live host','live'); invite=s.invite(host['token'])
    with pytest.raises(ValueError): s.receive(invite['code'],environment='paper')
    assert s.receive(invite['code'],environment='live')['environment']=='live'

def test_new_receiver_starts_at_join_not_recent_trade_history(tmp_path):
    s=service(tmp_path); host=s.create('Host','paper')
    old=event(); s.relay.publish(host['token'],old)
    follower=s.receive(s.invite(host['token'])['code'])
    assert s.relay.read(follower['token'],0)['events']==[]
    fresh=event(); s.relay.publish(host['token'],fresh)
    assert [r['event']['event_id'] for r in s.relay.read(follower['token'],0)['events']]==[fresh.event_id]

def test_codes_and_tokens_are_hashed_in_database(tmp_path):
    s=service(tmp_path); host=s.create('Host','live'); invite=s.invite(host['token'])
    raw=(tmp_path/'relay.sqlite3').read_bytes()
    assert invite['code'].encode() not in raw
    assert host['token'].encode() not in raw

def test_public_provisioning_is_opt_in_and_rate_limited(tmp_path):
    s=service(tmp_path)
    app=FastAPI(); app.include_router(connection_router(s, enabled=False))
    with TestClient(app) as client:
        assert client.post('/api/connect/host',json={'name':'Host','environment':'paper'}).status_code==503
    app=FastAPI(); app.include_router(connection_router(s, enabled=True))
    with TestClient(app) as client:
        for _ in range(5):
            assert client.post('/api/connect/host',json={'name':'Host','environment':'paper'}).status_code==200
        assert client.post('/api/connect/host',json={'name':'Host','environment':'paper'}).status_code==429

def test_invitation_exchange_over_http(tmp_path):
    s=service(tmp_path); app=FastAPI()
    app.include_router(connection_router(s, enabled=True))
    app.include_router(sync_router(s.relay, lambda: None))
    with TestClient(app) as client:
        host=client.post('/api/connect/host',json={'name':'Host','environment':'paper'}).json()
        invitation=client.post('/api/connect/invite',headers={'Authorization':'Bearer '+host['token']}).json()
        response=client.post('/api/connect/receive',json={'code':invitation['code']})
        assert response.status_code==200
        assert response.json()['role']=='follower'
        assert client.post('/api/connect/receive',json={'code':invitation['code']}).status_code==401
