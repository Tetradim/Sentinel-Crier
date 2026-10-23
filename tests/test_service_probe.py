import httpx
import pytest
from scripts.configure_connection_service import probe, validate

def test_probe_checks_readiness_without_following_redirects():
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'status':'ok','protocol':1,'pairing_enabled':True}))) as client:
        assert probe('https://relay.example',client)['status']=='ok'
    for value in [{'status':'ok','protocol':1,'pairing_enabled':False},{'status':'degraded','protocol':1,'pairing_enabled':True}]:
        with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=value))) as client:
            with pytest.raises(ValueError): probe('https://relay.example',client)

def test_supabase_gateway_probe_preserves_prefix():
    def respond(request):
        assert request.url.path=='/functions/v1/crier/health'
        return httpx.Response(200,json={'status':'ok','protocol':1,'pairing_enabled':True})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert probe('https://project.supabase.co/functions/v1/crier/',client)['status']=='ok'
    with pytest.raises(ValueError): validate('https://project.supabase.co/functions/v1/other')

@pytest.mark.parametrize('origin',['http://relay.example','https://user:password@relay.example','https://relay.example/path','https://relay.example?token=secret','https://relay.example:99999'])
def test_reject_unsafe_origin(origin):
    with pytest.raises(ValueError): validate(origin)
