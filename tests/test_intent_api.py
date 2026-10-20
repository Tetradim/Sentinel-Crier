import asyncio
from fastapi.testclient import TestClient
from crier.app import create_app
from crier.config import Config
from test_intent_relay import event

def test_relay_routes_and_pc_console(tmp_path):
    app=create_app(Config(data_dir=tmp_path,token='a'*32))
    with TestClient(app) as client:
        auth={'Authorization':'Bearer '+'a'*32}
        assert client.get('/intent').status_code==200
        assert client.get('/api/device').status_code==401
        pair=client.post('/api/sync/channels',headers=auth,json={'name':'Host','environment':'paper'}).json()
        host={'Authorization':'Bearer '+pair['host_token']}; follower={'Authorization':'Bearer '+pair['follower_token']}
        e=event().to_dict()
        assert client.post('/api/sync/events',headers=host,json=e).status_code==200
        assert client.post('/api/sync/events',headers=follower,json=e).status_code==401
        assert client.get('/api/sync/events?wait=0',headers=follower).json()['events'][0]['event']==e
        assert 'host_token' not in client.get('/api/sync/channels',headers=auth).text
        assert client.post('/api/sync/revoke/'+pair['id'],headers=auth).status_code==200
        assert client.get('/api/sync/events?wait=0',headers=follower).status_code==401
