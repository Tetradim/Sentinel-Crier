import base64
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('update_release', ROOT/'desktop/update_release.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_release_signature_covers_installer_and_compatibility(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    artifact = tmp_path/'SentinelCrier-0.3.0-Windows-Setup.exe'
    artifact.write_bytes(b'synthetic installer')
    policy = dict(schema=1, enabled=True, repository='Tetradim/Sentinel-Crier', channel='stable', public_keys={'release-1':public}, publisher_thumbprints=[])
    envelope = module().signed_release(artifact, '0.3.0', 'a'*40, '0.2.0', '0.2.9', 'Changes and recovery: keep original profile.', policy, key, 'release-1')
    payload = base64.b64decode(envelope['payload'], validate=True)
    key.public_key().verify(base64.b64decode(envelope['signature'], validate=True), payload)
    row = json.loads(payload)
    assert row['compatibility']['min_source_version'] == '0.2.0'
    assert row['installer']['bytes'] == artifact.stat().st_size
    assert row['installer']['url'].endswith('/v0.3.0/'+artifact.name)
    assert 'PRIVATE' not in json.dumps(envelope)
    with pytest.raises(ValueError):
        module().signed_release(artifact, '0.3.0', 'a'*40, '0.2.0', '0.2.9', 'notes', policy, Ed25519PrivateKey.generate(), 'release-1')
    import httpx
    from crier.updates import UpdateClient
    base='https://github.com/Tetradim/Sentinel-Crier/releases/download/v0.3.0/'
    def respond(request):
        if request.url.host=='api.github.com':
            return httpx.Response(200,json={'tag_name':'v0.3.0','draft':False,'prerelease':False,'assets':[{'name':'SentinelCrier-update.json','browser_download_url':base+'SentinelCrier-update.json'}]})
        if request.url.path.endswith('.json'):return httpx.Response(200,json=envelope)
        return httpx.Response(200,content=artifact.read_bytes())
    client=UpdateClient(policy,'0.2.0',staging_root=tmp_path/'stage',client=httpx.Client(transport=httpx.MockTransport(respond)))
    assert client.check()['status']=='available'
    assert client.download().read_bytes()==artifact.read_bytes()
    assert client.verify_staged().is_file()


@pytest.mark.parametrize('minimum,maximum,notes', [('0.3.1','0.4.0','notes'),('0.2.9','0.2.0','notes'),('0.2.0','0.2.9','')])
def test_release_refuses_untested_or_ambiguous_source_ranges(tmp_path, minimum, maximum, notes):
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    artifact = tmp_path/'SentinelCrier-0.3.0-Windows-Setup.exe'
    artifact.write_bytes(b'test')
    policy = dict(schema=1, enabled=True, repository='Tetradim/Sentinel-Crier', channel='stable', public_keys={'release-1':public}, publisher_thumbprints=[])
    with pytest.raises(ValueError):
        module().signed_release(artifact,'0.3.0','a'*40,minimum,maximum,notes,policy,key,'release-1')
