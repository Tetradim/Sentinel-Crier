from fastapi.testclient import TestClient
from crier.config import Config
from crier.connection_server import create_connection_app


def test_standalone_relay_has_no_broker_control_and_can_pair(tmp_path):
    app=create_connection_app(Config(data_dir=tmp_path,token='o'*32,public_pairing_enabled=True))
    with TestClient(app) as client:
        assert client.get('/health').json()['pairing_enabled']
        assert client.post('/api/device/command',json={}).status_code==404
        host=client.post('/api/connect/host',json={'name':'Host','environment':'paper'}).json()
        invite=client.post('/api/connect/invite',headers={'Authorization':'Bearer '+host['token']}).json()
        assert client.post('/api/connect/receive',json={'code':invite['code'],'environment':'live'}).status_code==422
        assert client.post('/api/connect/receive',json={'code':invite['code'],'environment':'paper'}).status_code==200
        assert client.get('/api/sync/channels').status_code==401
        assert client.get('/connect').headers['referrer-policy']=='no-referrer'


def test_body_limit_rejects_large_chunked_requests(tmp_path):
    with TestClient(create_connection_app(Config(data_dir=tmp_path,token='o'*32))) as client:
        assert client.post('/api/connect/host',content=iter([b'x'*20000,b'x'*20000])).status_code==413
