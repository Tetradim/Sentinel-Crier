import asyncio
import json
import pytest
import httpx
from fastapi import FastAPI
from crier.connection_client import ConnectionClient, parse_invitation, validate_origin
from crier.intent_relay import IntentRelay
from crier.quick_connect import ConnectionService, connection_router

@pytest.mark.parametrize('url',['http://example.com','https://user:password@example.com','https://example.com/path','https://example.com?secret=x','https://relay.example/functions/v1/other','https://relay.example/functions/v1/crier/other','https://relay.example/functions/v1/%63rier','https://relay.example/functions/v1/crier?','https://relay.example/#','https://@relay.example','https://relay.example:0',''])
def test_reject_non_origin_service_addresses(url):
    with pytest.raises(ValueError): validate_origin(url)

def test_share_link_supplies_service_without_manual_url():
    assert parse_invitation('https://relay.example/connect#ABCD-EFGH-IJKL-MNOP', '') == (
        'https://relay.example','ABCDEFGHIJKLMNOP')
    with pytest.raises(ValueError): parse_invitation('https://relay.example/other#ABCDEFGHIJKLMNOP','')

@pytest.mark.parametrize('base',['https://relay.example','https://project.supabase.co/functions/v1/crier'])
def test_client_persists_pairing_and_reuses_host_after_restart(tmp_path, base):
    async def run():
        service=ConnectionService(IntentRelay(tmp_path/'server.db'))
        app=FastAPI(); app.include_router(connection_router(service,True), prefix='/functions/v1/crier' if 'supabase.co' in base else '')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
            host=ConnectionClient(tmp_path/'host.secret', http=http)
            first=await host.host(base+'/','paper')
            restarted=ConnectionClient(tmp_path/'host.secret',http=http)
            second=await restarted.host('', 'paper')
            assert first['pair']==second['pair']
            assert len(service.relay.channels())==1
            follower=ConnectionClient(tmp_path/'follower.secret',http=http)
            result=await follower.receive(first['invitation'],'')
            assert result['pair']['role']=='follower'
            assert result['pair']['url']==base
            assert first['invitation'].startswith(base+'/connect#')
            assert (await follower.receive('', ''))['pair']==result['pair']
            with pytest.raises(ValueError): await follower.host('', 'paper')
            with pytest.raises(ValueError): await follower.receive(second['invitation'], '')
    asyncio.run(run())


def test_supabase_invitation_preserves_gateway_and_canonicalizes_base():
    base='https://project.supabase.co/functions/v1/crier'
    assert validate_origin(base+'/') == base
    assert parse_invitation(base+'/connect#ABCDEFGHIJKLMNOP','') == (base,'ABCDEFGHIJKLMNOP')
    for path in ('/other/connect', '/functions/v1/other/connect', '/functions/v1/crier/other/connect', '/functions/v1/crier//connect'):
        with pytest.raises(ValueError):
            parse_invitation('https://project.supabase.co'+path+'#ABCDEFGHIJKLMNOP','')
