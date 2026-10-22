"""Best-effort diagnostic transport, separate from order execution."""
import asyncio
from datetime import datetime, timezone
import json
import time
import httpx
from .trade_diagnostics import validate_quote


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


class DiagnosticsClient:
    def __init__(self, device):
        self.device = device
        self.clock = None
        with device.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS diagnostic_jobs(event_id TEXT PRIMARY KEY,pair TEXT,trade_id TEXT,payload TEXT,observation TEXT,attempts INTEGER DEFAULT 0,next_try REAL DEFAULT 0,done INTEGER DEFAULT 0)')

    def observe(self, event, stage):
        now = time.time() * 1000
        clock = self.clock
        valid = clock and clock['pair'] == self.device.fingerprint and 0 <= now-clock['sampled'] <= 60000 and abs((now-clock['sampled'])-(time.monotonic()-clock['mono'])*1000) <= 100
        observation = dict(stage=stage, observed_at=iso(now), clock_offset_ms=clock['offset'] if valid else None,
                           clock_uncertainty_ms=clock['uncertainty'] if valid else None,
                           clock_sampled_at=iso(clock['sampled']) if valid else None, quote=None, quote_error='capture_pending')
        with self.device.db() as db:
            db.execute('INSERT OR IGNORE INTO diagnostic_jobs(event_id,pair,trade_id,payload,observation) VALUES (?,?,?,?,?)',
                       (event.event_id,self.device.fingerprint,event.trade_id,event.model_dump_json(),json.dumps(observation)))

    async def sample_clock(self, client, pair):
        wall = time.time()*1000; mono = time.monotonic()
        response = await client.get(pair['url'].rstrip('/')+'/api/sync/clock', headers={'Authorization':'Bearer '+pair['token']})
        response.raise_for_status()
        end = time.time()*1000; elapsed = (time.monotonic()-mono)*1000
        server = response.json()['server_time_ms']
        if not isinstance(server,(int,float)) or isinstance(server,bool) or abs(end-wall-elapsed)>100:
            self.clock = None
            return
        import math
        if not math.isfinite(server) or elapsed > 60000 or abs(server-(wall+end)/2)>604800000:
            self.clock = None
            return
        self.clock = dict(pair=self.device.fingerprint,offset=server-(wall+end)/2,uncertainty=elapsed/2,sampled=end,mono=time.monotonic())

    async def capture(self, client, event, observation):
        broker = self.device.broker
        headers = getattr(broker,'data_headers',None)
        if not headers:
            observation['quote_error'] = 'market_data_credentials_unavailable'
            return
        try:
            symbol = event['symbol']
            if event['asset']=='option':
                url='https://data.alpaca.markets/v1beta1/options/quotes/latest'
                params={'symbols':symbol,'feed':'opra'}
            else:
                from urllib.parse import quote
                url='https://data.alpaca.markets/v2/stocks/'+quote(symbol,safe='')+'/quotes/latest'
                params={'feed':'iex'}
            response=await client.get(url,params=params,headers=headers)
            response.raise_for_status()
            body=response.json()
            raw=body['quotes'][symbol] if event['asset']=='option' else body['quote']
            result=validate_quote(dict(source='alpaca:opra' if event['asset']=='option' else 'alpaca:iex',quote_timestamp=raw['t'],bid=raw.get('bp'),ask=raw.get('ap'),last=None))
            stamp=datetime.fromisoformat(result['quote_timestamp']).timestamp()*1000
            observed=datetime.fromisoformat(observation['observed_at']).timestamp()*1000+(observation['clock_offset_ms'] or 0)
            capture_now=time.time()*1000+(observation['clock_offset_ms'] or 0)
            if abs(observed-stamp)>5000 or not 0 <= capture_now-stamp <= 5000:
                raise ValueError('stale_quote')
            observation['quote']={k:result[k] for k in ('source','quote_timestamp','bid','ask','last')}
            observation['quote_error']=None
        except httpx.HTTPStatusError as exc:
            observation['quote_error']='market_data_http_'+str(exc.response.status_code)
        except Exception:
            observation['quote_error']='quote_unavailable_or_stale'

    async def run(self, stop):
        next_clock=0
        async with httpx.AsyncClient(timeout=3,trust_env=False,follow_redirects=False) as client:
            while not stop.is_set():
                pair=dict(self.device.pair or {})
                if pair:
                    if time.monotonic()>=next_clock or (self.clock and self.clock['pair']!=self.device.fingerprint):
                        try: await self.sample_clock(client,pair)
                        except Exception: self.clock=None
                        next_clock=time.monotonic()+20
                    with self.device.db() as db:
                        jobs=[dict(row) for row in db.execute('SELECT * FROM diagnostic_jobs WHERE pair=? AND done=0 AND next_try<=? ORDER BY rowid LIMIT 8',(self.device.fingerprint,time.time()))]
                    for job in jobs:
                        if stop.is_set(): break
                        observation=json.loads(job['observation'])
                        try:
                            if observation['quote_error']=='capture_pending':
                                await self.capture(client,json.loads(job['payload']),observation)
                                with self.device.db() as db:
                                    db.execute('UPDATE diagnostic_jobs SET observation=? WHERE event_id=?',(json.dumps(observation),job['event_id']))
                                self.device._trace(job['trade_id'],'diagnostic_observation',event_id=job['event_id'],actor='host' if observation['stage']=='sender' else 'local',observation=observation)
                            if observation['stage']=='sender':
                                with self.device.db() as db:
                                    sent=db.execute("SELECT state FROM outgoing WHERE id=?",(job['event_id'],)).fetchone()
                                if not sent or sent[0]!='sent': continue
                            headers={'Authorization':'Bearer '+pair['token']}
                            url=pair['url'].rstrip('/')+'/api/sync/diagnostics'
                            response=await client.post(url,headers=headers,json={'event_id':job['event_id'],'observation':observation})
                            response.raise_for_status()
                            response=await client.get(url,headers=headers,params={'event_id':job['event_id']})
                            response.raise_for_status()
                            observations=response.json()['observations']
                            for item in observations:
                                # Store remote evidence for offline reports; report deduplicates actors.
                                self.device._trace(job['trade_id'],'diagnostic_observation',event_id=job['event_id'],actor=item['actor'],observation=item['observation'])
                            complete=observation['stage']=='sender' or (any(x['observation']['stage']=='sender' for x in observations) and any(x['observation']['stage']=='receiver' for x in observations))
                            with self.device.db() as db:
                                db.execute('UPDATE diagnostic_jobs SET done=? WHERE event_id=?',(int(complete),job['event_id']))
                        except Exception:
                            pass
                        finally:
                            attempts=job['attempts']+1
                            with self.device.db() as db:
                                db.execute('UPDATE diagnostic_jobs SET attempts=?,next_try=?,done=CASE WHEN ?>=30 THEN 1 ELSE done END WHERE event_id=?',(attempts,time.time()+min(60,2**min(attempts,6)),attempts,job['event_id']))
                try: await asyncio.wait_for(stop.wait(),.25)
                except TimeoutError: pass
