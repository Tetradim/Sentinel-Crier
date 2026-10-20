"""Owner controls and a separate least-privilege fill ingestion endpoint."""
import os
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from .mirror import Mirror, MirrorEvent, AlpacaMirrorBroker
from .lock import AlreadyRunningError

class PairName(BaseModel):
    name: str = Field(min_length=1, max_length=60)
class Follow(BaseModel):
    enabled: bool

def configure_mirror(config):
    key = os.getenv('CRIER_MIRROR_ALPACA_KEY', '')
    secret = os.getenv('CRIER_MIRROR_ALPACA_SECRET', '')
    broker = AlpacaMirrorBroker(os.getenv('CRIER_MIRROR_ENV', 'paper'), key, secret) if key and secret else None
    return Mirror(config.data_dir / 'mirror.sqlite3', broker)

def mirror_router(mirror, auth):
    router = APIRouter(prefix='/api/mirror')
    @router.get('', dependencies=[Depends(auth)])
    def status(): return mirror.status()
    @router.post('/pairs', dependencies=[Depends(auth)])
    def pair(value: PairName):
        try: return mirror.pair(value.name)
        except Exception: raise HTTPException(422, 'Cannot pair. Check receiver broker credentials and environment.')
    @router.put('/pairs/{identity}', dependencies=[Depends(auth)])
    def follow(identity: str, value: Follow):
        try: mirror.follow(identity, value.enabled)
        except ValueError: raise HTTPException(404, 'Pair not found')
        return {'enabled': value.enabled}
    @router.delete('/pairs/{identity}', dependencies=[Depends(auth)])
    def revoke(identity: str):
        mirror.revoke(identity)
        return {'revoked': True}
    @router.post('/events')
    def receive(value: MirrorEvent, authorization: str = Header(default='')):
        if not authorization.startswith('Bearer '): raise HTTPException(401, 'Pair first')
        try: return mirror.receive(authorization[7:], value)
        except PermissionError: raise HTTPException(401, 'Pairing invalid or revoked')
        except ValueError as exc: raise HTTPException(422, str(exc))
        except AlreadyRunningError: raise HTTPException(503, 'Receiver busy; retry same event')
    @router.post('/reconcile', dependencies=[Depends(auth)])
    def reconcile():
        mirror.reconcile()
        return mirror.status()
    return router
