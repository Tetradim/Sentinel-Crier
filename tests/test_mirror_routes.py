from fastapi.testclient import TestClient
from crier.app import create_app
from crier.config import Config
from test_mirror import Broker, event

def test_pair_follow_receive_and_revoke(tmp_path):
    app = create_app(Config(data_dir=tmp_path, token='a'*32))
    app.state.mirror.broker = Broker()
    client = TestClient(app); owner = {'Authorization': 'Bearer ' + 'a'*32}
    assert client.post('/api/mirror/pairs', json={'name':'Customer'}).status_code == 401
    pair = client.post('/api/mirror/pairs', json={'name':'Customer'}, headers=owner).json()
    customer = {'Authorization': 'Bearer ' + pair['token']}
    assert client.get('/api/mirror', headers=customer).status_code == 401
    assert client.put('/api/mirror/pairs/'+pair['id'], json={'enabled':True}, headers=owner).status_code == 200
    fill = event().model_dump(mode='json')
    response = client.post('/api/mirror/events', json=fill, headers=customer)
    assert response.status_code == 200 and response.json()['state'] == 'accepted'
    assert 'token' not in client.get('/api/mirror', headers=owner).text
    client.delete('/api/mirror/pairs/'+pair['id'], headers=owner)
    assert client.post('/api/mirror/events', json=fill, headers=customer).status_code == 401
    assert client.get('/mirror').status_code == 200
