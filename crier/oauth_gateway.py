"""Explicit server composition for provider authorization; not installed in the relay.

Run behind trusted TLS without query/body access logging. Native credential
installation and customer login UI are separate integration requirements.
"""
import asyncio
import hashlib
import re
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from .connection_server import BodyLimit
from .oauth_flows import FlowRejected
from .oauth_providers import OAuthApplication

MESSAGE = 'Provider connection request rejected.'
FLOW = r'^[A-Za-z0-9_-]{43}$'


def _reject(status=400):
    raise HTTPException(status, MESSAGE)


def _origin(value):
    if not isinstance(value, str) or len(value) > 2048 or not value.isascii() or any(ord(c) <= 32 for c in value):
        raise ValueError(MESSAGE)
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or parsed.netloc != parsed.hostname
            or '\\' in value or '?' in value or '#' in value):
        raise ValueError(MESSAGE)
    return value


class SupabaseOwnerVerifier:
    """Validate an actual nonanonymous Auth user remotely; never trust profile claims."""
    def __init__(self, project_url, publishable_key, *, client=None):
        self.project_url = _origin(project_url)
        if not re.fullmatch(r'https://[a-z]{20}\.supabase\.co', self.project_url):
            raise ValueError(MESSAGE)
        if not isinstance(publishable_key, str) or not publishable_key or len(publishable_key) > 4096:
            raise ValueError(MESSAGE)
        self.key, self.client = publishable_key, client

    async def __call__(self, authorization):
        if (not isinstance(authorization, str) or not authorization.startswith('Bearer ')
                or not re.fullmatch(r'Bearer [!-~]{1,8192}', authorization)):
            raise ValueError(MESSAGE)
        owned = self.client is None
        client = self.client or httpx.AsyncClient(trust_env=False, follow_redirects=False)
        try:
            async with client.stream('GET', self.project_url+'/auth/v1/user',
                    headers={'apikey':self.key, 'Authorization':authorization},
                    timeout=15, follow_redirects=False, auth=None) as response:
                if response.status_code != 200:
                    raise ValueError(MESSAGE)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 65536:
                        raise ValueError(MESSAGE)
                    body.extend(chunk)
            import json
            user = json.loads(body)
            identity = user['id']
            if user.get('is_anonymous') is not False or str(UUID(identity)) != identity:
                raise ValueError(MESSAGE)
            return identity
        except Exception:
            raise ValueError(MESSAGE) from None
        finally:
            if owned:
                await client.aclose()

    async def browser(self, request):
        # The separately configured login/BFF must set this host-only HttpOnly
        # session cookie. Never put a customer JWT into the browser-launch URL.
        token = request.cookies.get('__Host-crier-session', '')
        return await self('Bearer '+token)


class Begin(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: str = Field(max_length=16)
    purpose: str = Field(max_length=16)
    environment: str = Field(max_length=16)
    challenge: str = Field(pattern=r'^[0-9a-f]{64}$')


class Flow(BaseModel):
    model_config = ConfigDict(extra='forbid')
    flow: str = Field(pattern=FLOW)


class Redeem(Flow):
    proof: str = Field(pattern=FLOW, repr=False)


def _cookie(state):
    return '__Host-crier-oauth-'+hashlib.sha256(state.encode()).hexdigest()[:24]


def create_oauth_app(*, store, applications, authenticate, public_origin, authenticate_browser=None, client_factory=None):
    """Require explicit trusted authentication, applications and external-key store."""
    origin = _origin(public_origin)
    if not applications or not callable(authenticate) or not callable(authenticate_browser):
        raise ValueError(MESSAGE)
    applications = dict(applications)
    for provider, application in applications.items():
        if (not isinstance(application, OAuthApplication) or application.provider != provider
                or application.callback != origin+'/oauth/callback/'+provider):
            raise ValueError(MESSAGE)
    make_client = client_factory or (lambda: httpx.AsyncClient(trust_env=False, follow_redirects=False))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimit, maximum=8192)

    @app.middleware('http')
    async def private(request, call_next):
        if request.url.scheme != 'https' or len(request.scope.get('query_string', b'')) > 8192:
            response = JSONResponse({'detail':MESSAGE}, status_code=400)
        else:
            response = await call_next(request)
        response.headers.update({'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer',
            'X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    @app.exception_handler(RequestValidationError)
    async def validation(request, exception):
        return JSONResponse({'detail':MESSAGE}, status_code=400)

    @app.exception_handler(FlowRejected)
    async def rejected(request, exception):
        return JSONResponse({'detail':MESSAGE}, status_code=400)

    async def owner(request: Request):
        headers = request.headers.getlist('authorization')
        if len(headers) != 1 or len(headers[0]) > 8199:
            _reject(401)
        try:
            identity = await asyncio.wait_for(authenticate(headers[0]), 20)
            if not isinstance(identity, str) or not identity or len(identity) > 200 or any(ord(c) <= 32 for c in identity):
                _reject(401)
            return identity
        except Exception:
            _reject(401)

    async def browser_owner(request: Request):
        try:
            identity = await asyncio.wait_for(authenticate_browser(request), 20)
            if not isinstance(identity, str) or not identity or len(identity) > 200 or any(ord(c) <= 32 for c in identity):
                _reject(401)
            return identity
        except Exception:
            _reject(401)

    def query(request, allowed, required):
        values = request.query_params
        if any(key not in allowed or len(values.getlist(key)) != 1 for key in values) or any(key not in values for key in required):
            _reject()
        return dict(values)

    @app.post('/oauth/begin')
    async def begin(value: Begin, identity=Depends(owner)):
        if value.provider not in applications:
            _reject()
        result = store.create(identity, value.provider, value.purpose, value.environment, value.challenge)
        return {key:result[key] for key in ('flow','expires_at')} | {
            'launch_url':origin+'/oauth/browser?ticket='+result['launch_ticket']}

    @app.get('/oauth/browser')
    async def browser(request: Request, identity=Depends(browser_owner)):
        value = query(request, {'ticket'}, {'ticket'})
        flow = store.launch(value['ticket'], owner=identity)
        response = RedirectResponse(applications[flow['provider']].authorization_url(
            flow['state'], flow['purpose'], flow['environment']), status_code=303)
        response.set_cookie(_cookie(flow['state']), flow['browser_binding'], secure=True,
            httponly=True, samesite='lax', max_age=300, path='/')
        return response

    @app.get('/oauth/callback/{provider}')
    async def callback(provider: str, request: Request, identity=Depends(browser_owner)):
        if provider not in applications:
            _reject()
        value = query(request, {'state','code','error','iss'}, {'state'})
        state = value['state']
        if (not re.fullmatch(FLOW, state) or bool(value.get('code')) == bool(value.get('error'))
                or (provider == 'discord' and value.get('iss') != 'https://discord.com')
                or (provider == 'alpaca' and 'iss' in value)):
            _reject()
        name = _cookie(state)
        binding = request.cookies.get(name, '')
        flow = store.claim_callback(provider, state, binding, owner=identity)
        try:
            if 'error' in value:
                store.fail(flow['flow'])
            else:
                async with make_client() as client:
                    grant = await asyncio.wait_for(applications[provider].exchange(
                        value['code'], flow['purpose'], flow['environment'], client), 30)
                store.complete(flow['flow'], grant)
        except asyncio.CancelledError:
            # The provider may have consumed the code. Retain the claimed,
            # uncertain exchange rather than making its code retryable.
            raise
        except Exception:
            # Invalid/ambiguous replies are not evidence that no token exists.
            # Cancellation or expiry may also have fenced out this late result.
            # Preserve that stage; only an explicit browser denial is definitive.
            pass
        response = RedirectResponse('sentinelcrier://oauth/complete?flow='+flow['flow'], status_code=303)
        response.delete_cookie(name, path='/', secure=True, httponly=True, samesite='lax')
        return response

    @app.post('/oauth/status')
    async def status(value: Flow, identity=Depends(owner)):
        return store.status(identity, value.flow)

    @app.post('/oauth/redeem')
    async def redeem(value: Redeem, identity=Depends(owner)):
        return store.redeem(identity, value.flow, value.proof)

    @app.post('/oauth/cancel')
    async def cancel(value: Redeem, identity=Depends(owner)):
        store.cancel(identity, value.flow, value.proof)
        return {'cancelled':True}

    return app
