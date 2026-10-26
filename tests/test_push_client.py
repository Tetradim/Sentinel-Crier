import asyncio
import json
import socket
import threading
import time
import httpx
import pytest
from fastapi import FastAPI
import uvicorn
from crier.push_client import frames, pages
from crier.intent_device import IntentDevice
from crier.intent_relay import IntentRelay, sync_router
from test_intent_device import Engine
from test_intent_relay import event


def test_parser_bounds_utf8_and_unknown_frames():
    async def run():
        response=httpx.Response(200,content='event: ready\r\ndata: {"text":"é"}\r\n\r\n'.encode())
        assert [item async for item in frames(response)]==[('ready',{'text':'é'})]
        assert [item async for item in frames(httpx.Response(200,content=b'event: extension\ndata: not json\n\n'))]==[]
        with pytest.raises(ValueError):
            _=[item async for item in frames(httpx.Response(200,content=b'data: '+b'a'*1048576))]
    asyncio.run(run())


def test_empty_stream_uses_bounded_poll_recovery():
    async def run():
        stop=asyncio.Event(); requests=[]; transports=[]
        def respond(request):
            requests.append(request.url.path)
            if request.url.path.endswith('/stream'): return httpx.Response(200,headers={'content-type':'text/event-stream'},content=b'')
            return httpx.Response(200,json={'events':[],'cursor':0})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            pair=dict(url='https://example.test',token='x'*40,role='follower')
            async for page in pages(client,pair,lambda:0,stop,lambda _:None,transports.append):
                assert page['events']==[]; stop.set(); break
        assert requests==['/api/sync/stream','/api/sync/events']
        assert transports==['connecting','poll']
    asyncio.run(run())


@pytest.mark.parametrize('count',[1,50])
def test_real_socket_push_does_not_wait_for_fill_or_poll(tmp_path,count):
    relay=IntentRelay(tmp_path/'relay.db'); pair=relay.create('Synthetic push','paper')
    app=FastAPI(); app.include_router(sync_router(relay,lambda:None)); polls=[]
    @app.middleware('http')
    async def record(request,call_next):
        if request.url.path.endswith('/events') and request.method=='GET': polls.append(request.url.path)
        return await call_next(request)
    listener=socket.socket(); listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True); thread.start()
    async def run():
        d=IntentDevice(tmp_path/'device')
        d.configure(dict(url=f'http://127.0.0.1:{port}',token=pair['follower_token'],environment='paper',role='follower'))
        d.engine=Engine(); stop=asyncio.Event(); task=asyncio.create_task(d.receive_loop(stop))
        try:
            for _ in range(200):
                if d.transport=='push': break
                await asyncio.sleep(.01)
            assert d.transport=='push'
            instructions=[event() for _ in range(count)]; start=time.monotonic()
            async with httpx.AsyncClient(trust_env=False) as client:
                for instruction in instructions:
                    response=await client.post(d.pair['url']+'/api/sync/events',headers={'Authorization':'Bearer '+pair['host_token']},json=instruction.to_dict())
                    assert response.status_code==200
            for _ in range(500):
                if len(d.engine.events)==count: break
                await asyncio.sleep(.01)
            assert [e.event_id for e in d.engine.events]==[e.event_id for e in instructions]
            if count==1: assert time.monotonic()-start<1.5
            assert polls==[]
            with d.db() as db: assert db.execute('SELECT cursor FROM cursors').fetchone()[0]==response.json()['cursor']
        finally:
            stop.set(); task.cancel(); await asyncio.gather(task,return_exceptions=True)
    try: asyncio.run(run())
    finally:
        server.should_exit=True; thread.join(5); listener.close()
    assert not thread.is_alive()
