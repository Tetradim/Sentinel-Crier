"""Dedicated internet relay: pairing and transport only, no brokerage workers."""
from contextlib import asynccontextmanager
import hmac
import os
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from .config import Config
from .intent_relay import IntentRelay, sync_router
from .quick_connect import ConnectionService, connection_router
from .lock import single_process


class BodyLimit:
    def __init__(self, app, maximum=32768):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope['type']!='http' or scope['method'] not in ('POST','PUT'):
            return await self.app(scope,receive,send)
        chunks=[]; size=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect': return
            chunk=message.get('body',b''); size+=len(chunk)
            if size>self.maximum:
                return await JSONResponse({'detail':'Request too large'},status_code=413)(scope,receive,send)
            chunks.append(chunk)
            if not message.get('more_body',False): break
        body=b''.join(chunks)
        sent=False
        async def replay():
            nonlocal sent
            if not sent:
                sent=True
                return {'type':'http.request','body':body,'more_body':False}
            return await receive()
        await self.app(scope,replay,send)


def create_connection_app(config=None):
    config=config or Config.from_env()
    relay=IntentRelay(config.data_dir/'intent-relay.sqlite3')
    @asynccontextmanager
    async def lifespan(app):
        # Long-poll notifications are in-process: deploy exactly one worker.
        with single_process(config.data_dir/'connection-server.lock'):
            yield
    app=FastAPI(title='Crier Connection Service',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(BodyLimit)
    def owner(authorization:str=Header(default='')):
        if not hmac.compare_digest(authorization.encode(),('Bearer '+config.token).encode()):
            raise HTTPException(401,'Owner authorization required')
    app.include_router(sync_router(relay,owner))
    app.include_router(connection_router(ConnectionService(relay),config.public_pairing_enabled))

    @app.middleware('http')
    async def private_responses(request,call_next):
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get('/health')
    def health():
        with relay.db() as db: db.execute('SELECT 1').fetchone()
        return {'status':'ok','pairing_enabled':config.public_pairing_enabled,'protocol':1}

    @app.get('/connect',response_class=HTMLResponse)
    def invitation_page():
        return '<!doctype html><title>Sentinel Crier invitation</title><h1>Open Sentinel Crier</h1><p>Copy the full invitation address, paste it into the app, and press Receive. Invitations are private, single use, and expire after ten minutes.</p>'

    return app


def main():
    import uvicorn
    uvicorn.run(create_connection_app(),host='0.0.0.0',port=int(os.getenv('PORT','8765')),access_log=False)


if __name__=='__main__': main()
