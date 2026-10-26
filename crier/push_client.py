"""Bounded authenticated SSE with durable polling recovery."""
import asyncio
import json
import httpx


async def frames(response):
    """Parse UTF-8 incrementally; bound a whole frame, including unknown fields."""
    pending=bytearray(); data=[]; name='message'; size=0
    async for chunk in response.aiter_bytes():
        pending.extend(chunk)
        if len(pending)>1048576: raise ValueError('Stream line too large')
        while b'\n' in pending:
            line,_,rest=pending.partition(b'\n'); pending=bytearray(rest)
            size+=len(line)+1
            if size>1048576: raise ValueError('Stream frame too large')
            text=line.rstrip(b'\r').decode('utf-8',errors='strict')
            if not text:
                if data: yield name,json.loads('\n'.join(data))
                data=[]; name='message'; size=0
            elif text.startswith('event:'): name=text[6:].lstrip(' ')
            elif text.startswith('data:'): data.append(text[5:].lstrip(' '))
    if pending or data: raise ValueError('Incomplete stream frame')


async def pages(client,pair,cursor,stop,on_dashboard,on_transport):
    """A stream failure gets one durable recovery poll before a reconnect."""
    headers={'Authorization':'Bearer '+pair['token']}
    base=pair['url'].rstrip('/')+'/api/sync'
    while not stop.is_set():
        try:
            on_transport('connecting')
            async with client.stream('GET',base+'/stream',params={'after':cursor()},headers=headers,timeout=httpx.Timeout(20,read=25)) as response:
                response.raise_for_status()
                if 'text/event-stream' not in response.headers.get('content-type',''): raise ValueError('Invalid stream response')
                async for kind,value in frames(response):
                    if stop.is_set(): return
                    if kind=='ready':
                        if value!={'version':1,'transport':'push'}: raise ValueError('Invalid stream greeting')
                        on_transport('push')
                    elif kind=='events' and pair['role']=='follower': yield value
                    elif kind=='dashboard': on_dashboard(value)
                    elif kind=='heartbeat':
                        if type(value.get('server_time_ms')) not in (int,float): raise ValueError('Invalid heartbeat')
            continue
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401,403): raise
            on_transport('poll')
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            on_transport('poll')
        if stop.is_set(): return
        if pair['role']=='follower':
            response=await client.get(base+'/events',params={'after':cursor(),'wait':20},headers=headers)
            response.raise_for_status(); yield response.json()
        if stop.is_set(): return
        try:
            response=await client.get(base+'/dashboard',headers=headers)
            response.raise_for_status(); on_dashboard(response.json())
        except (httpx.HTTPError,ValueError,KeyError,TypeError): pass
        try: await asyncio.wait_for(stop.wait(),1)
        except TimeoutError: pass
