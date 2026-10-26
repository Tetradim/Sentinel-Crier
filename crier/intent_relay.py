"""Broker-free durable relay. Separate publish/read secrets; no broker keys."""
import asyncio
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sqlite3
import time
from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from typing import Literal
from .intent_protocol import IntentEvent
from .diagnostic_protocol import DiagnosticRequest
from . import copy_relay
from .copy_dashboard import PresenceReport, StatusReport
from starlette.responses import StreamingResponse

class IntentRelay:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY,name TEXT,environment TEXT,host_digest TEXT UNIQUE,follower_digest TEXT UNIQUE,revoked INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS intents(cursor INTEGER PRIMARY KEY AUTOINCREMENT,channel TEXT,event_id TEXT,trade_id TEXT,sequence INTEGER,identity TEXT,payload TEXT,UNIQUE(channel,event_id),UNIQUE(channel,trade_id,sequence));
            CREATE INDEX IF NOT EXISTS stream_cursor ON intents(channel,cursor);
            CREATE TABLE IF NOT EXISTS receivers(id TEXT PRIMARY KEY,channel TEXT,token_digest TEXT UNIQUE,created REAL,revoked INTEGER DEFAULT 0,start_cursor INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS diagnostics(channel TEXT,event_id TEXT,actor TEXT,observation TEXT,PRIMARY KEY(channel,event_id,actor));
            ''')
            if 'start_cursor' not in {row['name'] for row in db.execute('PRAGMA table_info(receivers)')}:
                db.execute('ALTER TABLE receivers ADD COLUMN start_cursor INTEGER DEFAULT 0')
            copy_relay.initialize(db)
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15); db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    def create(self,name,environment):
        if not 1<=len(name.strip())<=60 or environment not in ('paper','live'): raise ValueError('Invalid channel')
        host=secrets.token_urlsafe(32); follower=secrets.token_urlsafe(32); identity=str(uuid4())
        with self.db() as db:
            db.execute('INSERT INTO channels VALUES (?,?,?,?,?,0)',(identity,name,environment,sha256(host.encode()).hexdigest(),sha256(follower.encode()).hexdigest()))
        return dict(id=identity,host_token=host,follower_token=follower,environment=environment)
    def authenticate(self,db,token,role):
        column='host_digest' if role=='host' else 'follower_digest'
        row=db.execute(f'SELECT * FROM channels WHERE {column}=? AND revoked=0',(sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None and role=='follower':
            row=db.execute('SELECT c.* FROM channels c JOIN receivers r ON r.channel=c.id WHERE r.token_digest=? AND c.revoked=0 AND r.revoked=0',
                           (sha256(token.encode()).hexdigest(),)).fetchone()
        if not row: raise PermissionError('Pairing invalid or revoked')
        return row
    def publish(self,token,event):
        payload=json.dumps(event.to_dict(),sort_keys=True,separators=(',',':'))
        identity=json.dumps([event.environment,event.symbol,event.asset])
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE'); channel=self.authenticate(db,token,'host')
            if event.environment!=channel['environment']: raise ValueError('Channel environment mismatch')
            old=db.execute('SELECT * FROM intents WHERE channel=? AND event_id=?',(channel['id'],event.event_id)).fetchone()
            if old:
                if old['payload']!=payload: raise ValueError('Event ID already used with different contents')
                return {'cursor':old['cursor']}
            prior=db.execute('SELECT identity FROM intents WHERE channel=? AND trade_id=? LIMIT 1',(channel['id'],event.trade_id)).fetchone()
            if prior and prior['identity']!=identity: raise ValueError('Trade identity cannot change')
            try:
                cursor=db.execute('INSERT INTO intents(channel,event_id,trade_id,sequence,identity,payload) VALUES (?,?,?,?,?,?)',
                                  (channel['id'],event.event_id,event.trade_id,event.sequence,identity,payload)).lastrowid
            except sqlite3.IntegrityError: raise ValueError('Trade sequence already used') from None
            return {'cursor':cursor}
    def read(self,token,after):
        with self.db() as db:
            channel=self.authenticate(db,token,'follower')
            receiver=db.execute('SELECT start_cursor FROM receivers WHERE token_digest=?',(sha256(token.encode()).hexdigest(),)).fetchone()
            if receiver: after=max(after,receiver['start_cursor'])
            rows=db.execute('SELECT cursor,payload FROM intents WHERE channel=? AND cursor>? ORDER BY cursor LIMIT 500',(channel['id'],after)).fetchall()
        return {'events':[{'cursor':r['cursor'],'event':json.loads(r['payload'])} for r in rows], 'cursor':rows[-1]['cursor'] if rows else after}
    def revoke(self,identity):
        with self.db() as db: db.execute('UPDATE channels SET revoked=1 WHERE id=?',(identity,))
    def channels(self):
        with self.db() as db: return [dict(r) for r in db.execute('SELECT id,name,environment,revoked FROM channels')]

    def diagnostic_identity(self, db, token):
        try:
            return self.authenticate(db, token, 'host'), 'host', 0
        except PermissionError:
            channel = self.authenticate(db, token, 'follower')
            receiver = db.execute('SELECT id,start_cursor FROM receivers WHERE token_digest=?',
                                  (sha256(token.encode()).hexdigest(),)).fetchone()
            return channel, receiver['id'] if receiver else 'legacy_receiver', receiver['start_cursor'] if receiver else 0

    def diagnostic_access(self, db, token, event_id):
        channel, actor, start = self.diagnostic_identity(db, token)
        event = db.execute('SELECT cursor FROM intents WHERE channel=? AND event_id=?',
                           (channel['id'], event_id)).fetchone()
        if event is None or (actor != 'host' and event['cursor'] <= start):
            raise LookupError('Event unavailable')
        return channel, actor

    def save_diagnostic(self, token, request):
        payload = json.dumps(request.observation.model_dump(), sort_keys=True, separators=(',', ':'))
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            channel, actor = self.diagnostic_access(db, token, request.event_id)
            if request.observation.stage != ('sender' if actor == 'host' else 'receiver'):
                raise HTTPException(403, 'Observation stage does not match device role')
            prior = db.execute('SELECT observation FROM diagnostics WHERE channel=? AND event_id=? AND actor=?',
                               (channel['id'], request.event_id, actor)).fetchone()
            if prior and prior['observation'] != payload:
                raise ValueError('Diagnostic evidence is immutable')
            if prior is None:
                db.execute('INSERT INTO diagnostics VALUES (?,?,?,?)',
                           (channel['id'], request.event_id, actor, payload))
        return {'stored': True}

    def read_diagnostics(self, token, event_id):
        with self.db() as db:
            channel, actor = self.diagnostic_access(db, token, event_id)
            rows = db.execute('SELECT actor,observation FROM diagnostics WHERE channel=? AND event_id=? AND actor IN (?,?) ORDER BY actor',
                              (channel['id'], event_id, 'host', actor)).fetchall()
        return {'observations': [{'actor': r['actor'], 'observation': json.loads(r['observation'])} for r in rows]}

class ChannelRequest(BaseModel):
    name: str=Field(min_length=1,max_length=60)
    environment: Literal['paper','live']='paper'

def sync_router(relay,auth):
    router=APIRouter(prefix='/api/sync'); changed=asyncio.Condition(); generation=0
    def token(authorization):
        if not authorization.startswith('Bearer '): raise HTTPException(401,'Pair first')
        return authorization[7:]
    @router.post('/status')
    @router.post('/presence')
    async def save_copy(request:Request,authorization:str=Header(default='')):
        nonlocal generation
        presence=request.url.path.endswith('/presence')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>8192: raise HTTPException(413,'Report too large')
        try: value=(PresenceReport if presence else StatusReport).model_validate_json(raw)
        except ValueError: raise HTTPException(422,'Invalid device report') from None
        try:
            async with changed:
                result=copy_relay.save(relay,token(authorization),value,presence=presence)
                generation+=1; changed.notify_all()
                return result
        except PermissionError: raise HTTPException(401,'Pairing invalid or revoked') from None
        except LookupError: raise HTTPException(404,'Event unavailable') from None
        except ValueError: raise HTTPException(409,'Report evidence conflicts') from None

    @router.get('/dashboard')
    def dashboard(response:Response,authorization:str=Header(default='')):
        response.headers['Cache-Control']='no-store'
        try: return copy_relay.snapshot(relay,token(authorization))
        except PermissionError: raise HTTPException(401,'Pairing invalid or revoked') from None

    @router.get('/stream')
    async def stream(request:Request,after:int=Query(default=0,ge=0),authorization:str=Header(default='')):
        secret=token(authorization)
        try:
            with relay.db() as db: _,actor,_=relay.diagnostic_identity(db,secret)
        except PermissionError: raise HTTPException(401,'Pairing invalid or revoked') from None
        def frame(name,value):
            data=('event: '+name+'\ndata: '+json.dumps(value,separators=(',',':'))+'\n\n').encode()
            if len(data)>1048576: raise ValueError('Snapshot exceeds stream bound')
            return data
        async def generate():
            cursor=after; started=time.monotonic()
            yield frame('ready',{'version':1,'transport':'push'})
            while time.monotonic()-started<90 and not await request.is_disconnected():
                try:
                    async with changed:
                        observed=generation
                        pages=[]
                        if actor!='host':
                            page=relay.read(secret,cursor)
                            if page['events']:
                                pages.append(frame('events',page)); cursor=page['cursor']
                        view=frame('dashboard',copy_relay.snapshot(relay,secret))
                    # Never hold the publication lock while a slow network consumer drains.
                    for page in pages: yield page
                    yield view
                    if pages: continue
                    heartbeat=False
                    async with changed:
                        if generation==observed:
                            try: await asyncio.wait_for(changed.wait(),15)
                            except TimeoutError: heartbeat=True
                    if heartbeat: yield frame('heartbeat',{'server_time_ms':time.time()*1000})
                except (PermissionError,ValueError): return
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
    @router.get('/clock')
    def clock(response:Response, authorization:str=Header(default='')):
        response.headers['Cache-Control'] = 'no-store'
        try:
            with relay.db() as db:
                relay.diagnostic_identity(db, token(authorization))
            return {'server_time_ms': time.time() * 1000}
        except PermissionError as exc:
            raise HTTPException(401, str(exc))

    @router.post('/diagnostics')
    async def save_diagnostic(request:Request, authorization:str=Header(default='')):
        nonlocal generation
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 8192:
                raise HTTPException(413, 'Diagnostic observation too large')
        try:
            value = DiagnosticRequest.model_validate_json(raw)
        except ValueError:
            # Do not echo untrusted values (including non-finite JSON numbers)
            # in FastAPI's default validation response.
            raise HTTPException(422, 'Invalid diagnostic observation') from None
        try:
            async with changed:
                result=relay.save_diagnostic(token(authorization), value)
                generation+=1; changed.notify_all()
                return result
        except PermissionError as exc:
            raise HTTPException(401, str(exc))
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @router.get('/diagnostics')
    def read_diagnostic(response:Response, event_id:str=Query(max_length=36), authorization:str=Header(default='')):
        response.headers['Cache-Control'] = 'no-store'
        try:
            return relay.read_diagnostics(token(authorization), event_id)
        except PermissionError as exc:
            raise HTTPException(401, str(exc))
        except LookupError as exc:
            raise HTTPException(404, str(exc))
    @router.post('/channels',dependencies=[Depends(auth)])
    def create(value:ChannelRequest): return relay.create(value.name,value.environment)
    @router.get('/channels',dependencies=[Depends(auth)])
    def channels(): return relay.channels()
    @router.post('/revoke/{identity}',dependencies=[Depends(auth)])
    async def revoke(identity:str):
        nonlocal generation
        async with changed:
            relay.revoke(identity); generation+=1; changed.notify_all()
        return {'revoked':True}
    @router.post('/events')
    async def publish(value:IntentEvent,authorization:str=Header(default='')):
        nonlocal generation
        try:
            async with changed:
                result=relay.publish(token(authorization),value); generation+=1; changed.notify_all(); return result
        except PermissionError as exc: raise HTTPException(401,str(exc))
        except ValueError as exc: raise HTTPException(409,str(exc))
    @router.get('/events')
    async def read(after:int=Query(default=0,ge=0),wait:float=Query(default=20,ge=0,le=25),authorization:str=Header(default='')):
        try:
            deadline=asyncio.get_running_loop().time()+wait
            async with changed:
                while True:
                    result=relay.read(token(authorization),after)
                    remaining=deadline-asyncio.get_running_loop().time()
                    if result['events'] or remaining<=0: return result
                    try: await asyncio.wait_for(changed.wait(),remaining)
                    except TimeoutError: return relay.read(token(authorization),after)
        except PermissionError as exc: raise HTTPException(401,str(exc))
    return router
