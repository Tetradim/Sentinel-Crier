"""Isolated synthetic paper-channel acceptance. Never connects to a brokerage."""
import argparse
import asyncio
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import time
from uuid import uuid4
import httpx
from crier.push_client import frames
from crier.copy_dashboard import dashboard_metrics


async def probe(origin):
    base=origin.rstrip('/'); host=None; receiver_id=None
    async with httpx.AsyncClient(timeout=30,trust_env=False,follow_redirects=False) as client:
        async def request(path,body=None,token=None,method='POST'):
            result=await client.request(method,base+path,json=body,headers={'Authorization':'Bearer '+token} if token else {})
            if result.status_code!=200: raise RuntimeError(f'Probe request failed: {path} HTTP {result.status_code}')
            return result.json()
        try:
            host=(await request('/api/connect/host',{'name':'Synthetic push acceptance '+str(uuid4())[:8],'environment':'paper'}))['token']
            invitation=await request('/api/connect/invite',{},host)
            receiver=(await request('/api/connect/receive',{'code':invitation['code']}))['token']
            dashboard=await request('/api/sync/dashboard',token=receiver,method='GET'); receiver_id=dashboard['actor']
            now=datetime.now(timezone.utc)
            event=dict(version=1,event_id=str(uuid4()),trade_id=str(uuid4()),sequence=1,action='enter',environment='paper',
                symbol='SPY261212C00750000',asset='option',quantity=1,limit_price='0.20',created_at=now.isoformat(),expires_at=(now+timedelta(seconds=20)).isoformat())
            async with client.stream('GET',base+'/api/sync/stream?after=0',headers={'Authorization':'Bearer '+receiver}) as response:
                if response.status_code!=200:
                    await response.aread()
                    reason=response.json().get('reason','unclassified')
                    if reason not in ('SUBSCRIBE_TIMEOUT','CHANNEL_ERROR','TIMED_OUT','CLOSED','SUBSCRIBE_UNAVAILABLE'): reason='unclassified'
                    raise RuntimeError(f'Stream unavailable HTTP {response.status_code}: {reason}')
                iterator=frames(response).__aiter__()
                kind,ready=await asyncio.wait_for(anext(iterator),10)
                assert kind=='ready' and ready==dict(version=1,transport='push')
                started=time.monotonic()
                published=await request('/api/sync/events',event,host)
                async def receive():
                    async for name,value in iterator:
                        if name=='events': return value
                    raise RuntimeError('Stream closed before durable event')
                delivered=await asyncio.wait_for(receive(),10)
                elapsed=(time.monotonic()-started)*1000
                assert delivered['events'][0]['event']['event_id']==event['event_id']
                assert delivered['events'][0]['cursor']==published['cursor']
            status=dict(version=1,event_id=event['event_id'],revision=1,observed_at=datetime.now(timezone.utc).isoformat(),state='closed',
                bought=1,sold=1,buy_premium='0.20',sell_premium='0.22',currency='USD',multiplier=100)
            await request('/api/sync/status',status,host); await request('/api/sync/status',status,receiver)
            snapshot=await request('/api/sync/dashboard',token=host,method='GET')
            assert {r['actor'] for r in snapshot['statuses']}=={'host',receiver_id}
            assert dashboard_metrics(snapshot['statuses'][0]['report'])['gross_realized_pnl']=='2.00'
            await request('/api/connect/receivers/'+receiver_id+'/revoke',{},host)
            denied=await client.get(base+'/api/sync/dashboard',headers={'Authorization':'Bearer '+receiver})
            assert denied.status_code==401
            return dict(version=1,scope='isolated synthetic paper channel; no broker or Discord consumers',
                tested_at=datetime.now(timezone.utc).isoformat(),service=base,push_delivered=True,
                durable_cursor_match=True,device_report_pnl='2.00',revoked_receiver_denied=True,
                measured_publish_round_trip_and_delivery_ms=round(elapsed,1),
                timing_note='One synthetic client/service sample; not cross-device, cross-state or broker execution latency.')
        finally:
            if host and receiver_id:
                try: await request('/api/connect/receivers/'+receiver_id+'/revoke',{},host)
                except Exception: pass


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('origin'); parser.add_argument('--report',type=Path)
    args=parser.parse_args(); report=asyncio.run(probe(args.origin)); rendered=json.dumps(report,indent=2)+'\n'
    if args.report: args.report.write_text(rendered,encoding='utf-8')
    print(rendered)
