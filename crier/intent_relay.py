"""Broker-free durable relay. Separate publish/read secrets; no broker keys."""
import asyncio
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sqlite3
from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Literal
from .intent_protocol import IntentEvent

class IntentRelay:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY,name TEXT,environment TEXT,host_digest TEXT UNIQUE,follower_digest TEXT UNIQUE,revoked INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS intents(cursor INTEGER PRIMARY KEY AUTOINCREMENT,channel TEXT,event_id TEXT,trade_id TEXT,sequence INTEGER,identity TEXT,payload TEXT,UNIQUE(channel,event_id),UNIQUE(channel,trade_id,sequence));
            CREATE INDEX IF NOT EXISTS stream_cursor ON intents(channel,cursor);
            ''')
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
            rows=db.execute('SELECT cursor,payload FROM intents WHERE channel=? AND cursor>? ORDER BY cursor LIMIT 500',(channel['id'],after)).fetchall()
        return {'events':[{'cursor':r['cursor'],'event':json.loads(r['payload'])} for r in rows], 'cursor':rows[-1]['cursor'] if rows else after}
    def revoke(self,identity):
        with self.db() as db: db.execute('UPDATE channels SET revoked=1 WHERE id=?',(identity,))
    def channels(self):
        with self.db() as db: return [dict(r) for r in db.execute('SELECT id,name,environment,revoked FROM channels')]

class ChannelRequest(BaseModel):
    name: str=Field(min_length=1,max_length=60)
    environment: Literal['paper','live']='paper'

def sync_router(relay,auth):
    router=APIRouter(prefix='/api/sync'); changed=asyncio.Condition()
    def token(authorization):
        if not authorization.startswith('Bearer '): raise HTTPException(401,'Pair first')
        return authorization[7:]
    @router.post('/channels',dependencies=[Depends(auth)])
    def create(value:ChannelRequest): return relay.create(value.name,value.environment)
    @router.get('/channels',dependencies=[Depends(auth)])
    def channels(): return relay.channels()
    @router.post('/revoke/{identity}',dependencies=[Depends(auth)])
    async def revoke(identity:str):
        async with changed:
            relay.revoke(identity); changed.notify_all()
        return {'revoked':True}
    @router.post('/events')
    async def publish(value:IntentEvent,authorization:str=Header(default='')):
        try:
            async with changed:
                result=relay.publish(token(authorization),value); changed.notify_all(); return result
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
