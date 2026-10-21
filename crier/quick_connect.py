"""Expiring device invitations. No broker credentials or order execution here."""
import base64
from hashlib import sha256
import re
import secrets
import time
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from .intent_relay import ChannelRequest


def digest(value):
    return sha256(value.encode()).hexdigest()


def normalize_code(code):
    code=re.sub(r'[\s-]', '', code).upper()
    if not re.fullmatch(r'[A-Z2-7]{16}', code):
        raise ValueError('Enter the 16-character invitation code.')
    return code


class ConnectionService:
    def __init__(self, relay):
        self.relay=relay
        with relay.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS invitations(code_digest TEXT PRIMARY KEY, channel TEXT, expires REAL);
                CREATE TABLE IF NOT EXISTS connection_limits(id TEXT PRIMARY KEY, window INTEGER, count INTEGER);
            ''')

    def limit(self, kind, identity, maximum, seconds=3600):
        now=int(time.time()); window=now//seconds
        key=digest(kind+':'+identity)
        with self.relay.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM connection_limits WHERE id=?',(key,)).fetchone()
            count=row['count'] if row and row['window']==window else 0
            if count>=maximum:
                raise ValueError('Too many connection requests. Try again later.')
            db.execute('INSERT OR REPLACE INTO connection_limits VALUES (?,?,?)',(key,window,count+1))

    def create(self, name, environment):
        with self.relay.db() as db:
            if db.execute('SELECT COUNT(*) FROM channels').fetchone()[0]>=10000:
                raise ValueError('Connection service capacity reached.')
        channel=self.relay.create(name,environment)
        # The legacy shared follower token is never distributed by this flow.
        return dict(token=channel['host_token'],environment=environment,role='host')

    def invite(self, token, now=None):
        now=time.time() if now is None else now
        code=base64.b32encode(secrets.token_bytes(10)).decode()
        with self.relay.db() as db:
            db.execute('BEGIN IMMEDIATE')
            host=self.relay.authenticate(db,token,'host')
            db.execute('DELETE FROM invitations WHERE expires<=?',(now,))
            db.execute('INSERT INTO invitations VALUES (?,?,?)',(digest(code),host['id'],now+600))
        return dict(code=code,expires_at=now+600)

    def receive(self, code, now=None, environment=None):
        code=normalize_code(code)
        now=time.time() if now is None else now
        token=secrets.token_urlsafe(32)
        with self.relay.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT i.*,c.environment FROM invitations i JOIN channels c ON i.channel=c.id WHERE i.code_digest=? AND i.expires>? AND c.revoked=0',
                           (digest(code),now)).fetchone()
            if not row:
                raise PermissionError('Invitation expired, already used or unavailable. Ask the host for a new one.')
            if environment is not None and row['environment']!=environment:
                raise ValueError('Select the invitation environment before receiving. The invitation has not been consumed.')
            cursor=db.execute('SELECT COALESCE(MAX(cursor),0) FROM intents WHERE channel=?',(row['channel'],)).fetchone()[0]
            db.execute('INSERT INTO receivers VALUES (?,?,?,?,0,?)',(str(uuid4()),row['channel'],digest(token),now,cursor))
            db.execute('DELETE FROM invitations WHERE code_digest=?',(digest(code),))
        return dict(token=token,environment=row['environment'],role='follower')

    def receivers(self, token):
        with self.relay.db() as db:
            host=self.relay.authenticate(db,token,'host')
            return [dict(r) for r in db.execute('SELECT id,created,revoked FROM receivers WHERE channel=? ORDER BY created',(host['id'],))]

    def revoke_receiver(self, token, identity):
        with self.relay.db() as db:
            host=self.relay.authenticate(db,token,'host')
            db.execute('UPDATE receivers SET revoked=1 WHERE id=? AND channel=?',(identity,host['id']))


class CodeRequest(BaseModel):
    code: str=Field(min_length=1,max_length=128)
    environment: Literal['paper','live']|None=None


def connection_router(service, enabled=False):
    router=APIRouter(prefix='/api/connect')

    def check(request, kind, maximum, seconds=3600):
        if not enabled:
            raise HTTPException(503,'Host/Receive setup is not enabled on this service.')
        try:
            service.limit(kind,request.client.host if request.client else 'unknown',maximum,seconds)
        except ValueError as exc:
            raise HTTPException(429,str(exc)) from None

    def token(authorization):
        if not authorization.startswith('Bearer ') or len(authorization)>300:
            raise HTTPException(401,'Host pairing required.')
        return authorization[7:]

    @router.post('/host')
    def host(value:ChannelRequest,request:Request):
        check(request,'host',5)
        try: return service.create(value.name,value.environment)
        except ValueError as exc: raise HTTPException(503,str(exc)) from None

    @router.post('/invite')
    def invite(request:Request,authorization:str=Header(default='')):
        check(request,'invite',60)
        try: return service.invite(token(authorization))
        except PermissionError as exc: raise HTTPException(401,str(exc)) from None

    @router.post('/receive')
    def receive(value:CodeRequest,request:Request):
        check(request,'receive',20,60)
        try: return service.receive(value.code,environment=value.environment)
        except PermissionError as exc: raise HTTPException(401,str(exc)) from None
        except ValueError as exc: raise HTTPException(422,str(exc)) from None

    @router.get('/receivers')
    def receivers(request:Request,authorization:str=Header(default='')):
        check(request,'list',120,60)
        try: return service.receivers(token(authorization))
        except PermissionError as exc: raise HTTPException(401,str(exc)) from None

    @router.post('/receivers/{identity}/revoke')
    def revoke(identity:str,request:Request,authorization:str=Header(default='')):
        check(request,'revoke',60)
        try: service.revoke_receiver(token(authorization),identity)
        except PermissionError as exc: raise HTTPException(401,str(exc)) from None
        return {'revoked':True}

    return router
