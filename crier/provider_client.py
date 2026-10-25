"""Pinned native customer auth and proof-bound provider handoff. No retries."""
import asyncio
import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from uuid import UUID
import httpx
from .device_secrets import load_secret, save_secret
from .oauth_return import OAuthReturnContext, PendingOAuthReturn

_SERVICE = re.compile(r'https://[a-z]{20}\.supabase\.co/functions/v1/crier-oauth', re.ASCII)
_OPAQUE = re.compile(r'[A-Za-z0-9_-]{43}', re.ASCII)


def validate_service(value):
    if not isinstance(value, str) or not _SERVICE.fullmatch(value):
        raise ValueError('Configure a trusted Supabase provider service.')
    return value


class ProviderClient:
    def __init__(self, base, session_path, *, client=None, clock=time.time):
        self.base = validate_service(base)
        self.path, self.clock = Path(session_path), clock
        self.client = client or httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False)
        self.owned = client is None
        self.session = None
        self.generation = 0
        self.pending = None
        self._begin_active = False
        self._inflight = None
        self.proof = None
        if self.path.exists():
            saved=json.loads(load_secret(self.path))
            if not isinstance(saved,dict) or saved.get('service_url')!=self.base:
                raise ValueError('Saved customer service mismatch; sign out before changing project.')
            self.session = self._session(saved.get('session'))

    def _session(self, row):
        try:
            UUID(row['user']['id'])
            if (not all(isinstance(row[k], str) and row[k] and len(row[k]) <= 16384 and all(33 <= ord(c) <= 126 for c in row[k]) for k in ('access_token','refresh_token'))
                    or row['token_type'] != 'bearer' or type(row['expires_in']) not in (int,float)
                    or not 0 < row['expires_in'] <= 86400): raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError('Invalid customer session.') from None
        return row

    def invalidate(self):
        self.generation += 1
        if self.pending: self.pending.invalidate()
        self.pending, self.proof = None, None
        self._inflight = None

    async def _request(self, route, body=None, *, protected=False):
        try:
            async with asyncio.timeout(20):
                return await self._request_inner(route,body,protected=protected)
        except TimeoutError:
            raise ValueError('Provider request timed out. Start a new flow; do not retry redemption.') from None

    async def _request_inner(self, route, body=None, *, protected=False):
        generation = self.generation
        if protected and not self.session: raise ValueError('Sign in to your Crier account first.')
        headers = {'Authorization':'Bearer '+self.session['access_token']} if protected else {}
        try:
            async with self.client.stream('GET' if body is None else 'POST', self.base+route,
                    json=body, headers=headers, follow_redirects=False) as response:
                if response.status_code != 200: raise ValueError('Provider service rejected the request. Sign in again or start a new connection.')
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>65536: raise ValueError('Invalid provider service response.')
                result=json.loads(data)
        except (httpx.HTTPError, json.JSONDecodeError):
            raise ValueError('Provider request could not be confirmed. Start a new flow; do not retry redemption.') from None
        if generation != self.generation: raise ValueError('Customer session changed; result discarded.')
        if not isinstance(result,dict): raise ValueError('Invalid provider service response.')
        return result

    async def capabilities(self):
        row=await self._request('/oauth/capabilities')
        if (row.get('version')!=1 or row.get('service_url')!=self.base
                or row.get('auth_project_url')!=self.base.split('/functions/')[0]
                or not isinstance(row.get('providers'),list)
                or any(p not in ('alpaca','discord') for p in row['providers'])):
            raise ValueError('Provider service identity mismatch.')
        return row

    async def login(self, email, password, *, signup=False):
        self.invalidate()
        self.session=None
        self.path.unlink(missing_ok=True)
        row=await self._request('/auth/signup' if signup else '/auth/login', {'email':email,'password':password})
        session=row.get('session') if signup else row
        if session is None:
            if signup and row.get('requiresEmailConfirmation') is True: return {'signed_in':False,'message':'Check your email, then sign in.'}
            raise ValueError('Customer session missing.')
        self.session=self._session(session)
        try: save_secret(self.path,json.dumps({'service_url':self.base,'session':self.session}))
        except BaseException:
            self.session=None
            raise
        return {'signed_in':True,'message':'Signed in. Choose a provider connection.'}

    async def refresh(self):
        if not self.session: raise ValueError('Sign in first.')
        owner=self.session['user']['id']
        refresh=self.session['refresh_token']
        self.invalidate()
        self.session=None
        self.path.unlink(missing_ok=True)
        row=self._session(await self._request('/auth/refresh', {'refresh_token':refresh}))
        if row['user']['id']!=owner: raise ValueError('Customer account changed.')
        save_secret(self.path,json.dumps({'service_url':self.base,'session':row}))
        self.session=row

    async def logout(self):
        self.invalidate()
        self.session=None
        self.path.unlink(missing_ok=True)
        return {'signed_in':False,'message':'Signed out. Saved broker recovery records retained.'}

    async def begin(self, provider, purpose, environment):
        if not self.session: raise ValueError('Sign in first.')
        if self.pending or self._begin_active: raise ValueError('Cancel the pending provider connection first.')
        context=OAuthReturnContext(self.session['user']['id'],provider,environment,purpose)
        proof=secrets.token_urlsafe(32)
        self._begin_active = True
        try:
            row=await self._request('/oauth/begin',dict(provider=provider,purpose=purpose,environment=environment,
                challenge=hashlib.sha256(proof.encode()).hexdigest()),protected=True)
        finally:
            self._begin_active = False
        launch=row.get('launch_url','')
        expiry=row.get('expires_at')
        if (not _OPAQUE.fullmatch(row.get('flow','')) or type(expiry) not in (int,float)
                or not self.clock()<expiry<=self.clock()+300
                or not re.fullmatch(re.escape(self.base)+r'/oauth/browser\?ticket=[A-Za-z0-9_-]{43}',launch)):
            raise ValueError('Invalid provider launch response.')
        self.pending=PendingOAuthReturn(row['flow'],context,expires_at=expiry)
        self.flow,self.context,self.proof=row['flow'],context,proof
        return launch

    async def cancel(self):
        outstanding = self._inflight or ((self.flow,self.proof) if self.pending else None)
        # Pending may have been consumed by an operation still awaiting I/O.
        self.invalidate()
        if outstanding:
            flow,proof=outstanding
            await self._request('/oauth/cancel',dict(flow=flow,proof=proof),protected=True)

    async def complete(self, uri):
        if not self.session or not self.pending: raise ValueError('No pending provider connection on this device.')
        context=OAuthReturnContext(self.session['user']['id'],self.context.provider,self.context.environment,self.context.purpose)
        if not self.pending.match_return(uri,self.flow,context,now=self.clock()): raise ValueError('Provider return rejected.')
        flow,proof=self.flow,self.proof
        self.pending,self.proof=None,None
        self._inflight=(flow,proof)
        status=await self._request('/oauth/status',{'flow':flow},protected=True)
        if status.get('stage')!='ready': raise ValueError('Provider connection is not ready. Start a new flow.')
        row=await self._request('/oauth/redeem',dict(flow=flow,proof=proof),protected=True)
        fields={'provider','environment','purpose','account_id','credential','guild_id','channel_id','scopes'}
        if (set(row)!=fields or (row['provider'],row['environment'],row['purpose'])!=(context.provider,context.environment,context.purpose)
                or not all(isinstance(row[k],str) for k in fields-{'scopes'})
                or not row['credential'] or len(row['credential'])>16384
                or any(ord(c)<33 or ord(c)>126 for c in row['credential'])
                or row['scopes'] != (['webhook.incoming'] if context.provider=='discord' else ['trading'] if context.purpose=='trade' else [])):
            raise ValueError('Provider grant identity mismatch.')
        if context.provider=='alpaca':
            if row['guild_id'] or row['channel_id']: raise ValueError('Invalid broker grant metadata.')
            try: UUID(row['account_id'])
            except ValueError: raise ValueError('Invalid broker identity.') from None
        else:
            from .delivery import validate_webhook
            validate_webhook(row['credential'])
            if row['account_id'] or not row['guild_id'].isdigit() or not row['channel_id'].isdigit(): raise ValueError('Invalid Discord identity.')
        self._inflight=None
        return row

    async def close(self):
        self.invalidate()
        if self.owned: await self.client.aclose()
