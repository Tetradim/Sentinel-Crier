import os
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from typing import Literal
from .intent_device import IntentDevice
from .intent_broker import AlpacaIntentBroker

class Pair(BaseModel):
    model_config=ConfigDict(extra='forbid')
    url:str; token:str; environment:Literal['paper','live']; role:Literal['host','follower']
class Command(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['enter','replace','cancel','exit']
    trade_id:str|None=None
    symbol:str|None=None
    asset:Literal['stock','option']|None=None
    quantity:int|None=Field(default=None,ge=1,le=1000)
    limit_price:str|None=None

def configure_device(config):
    values=[os.getenv('CRIER_INTENT_ALPACA_'+name,'') for name in ('KEY','SECRET','ACCOUNT')]
    broker=AlpacaIntentBroker(os.getenv('CRIER_INTENT_ENV','paper'),*values) if all(values) else None
    return IntentDevice(config.data_dir,broker)

def device_router(device,auth):
    router=APIRouter(prefix='/api/device',dependencies=[Depends(auth)])
    from .connection_client import ConnectionClient
    def connection(): return ConnectionClient(device.folder/'browser-connection.secret',existing=device.pair)

    @router.post('/connect/host')
    async def host(value:dict):
        try:
            result=await connection().host(value.get('origin',''),value.get('environment','paper'))
            device.configure(result['pair'])
            return dict(invitation=result['invitation'],expires_at=result['expires_at'],device=device.status())
        except (ValueError,TypeError) as exc: raise HTTPException(422,str(exc)) from None

    @router.post('/connect/receive')
    async def receive(value:dict):
        try:
            result=await connection().receive(value.get('invitation',''),value.get('origin',''))
            device.configure(result['pair'])
            return device.status()
        except (ValueError,TypeError) as exc: raise HTTPException(422,str(exc)) from None

    @router.get('/receivers')
    async def receivers():
        try: return await connection().receivers()
        except ValueError as exc: raise HTTPException(422,str(exc)) from None

    @router.post('/receivers/{identity}/revoke')
    async def revoke(identity:str):
        try: return await connection().revoke_receiver(identity)
        except ValueError as exc: raise HTTPException(422,str(exc)) from None

    @router.post('/retry-rejected')
    async def retry_rejected():
        try: return device.retry_rejected()
        except ValueError as exc: raise HTTPException(422,str(exc)) from None
    @router.get('')
    def status(): return device.status()
    @router.put('/pairing')
    async def configure(pair:Pair):
        try: device.configure(pair.model_dump()); return device.status()
        except ValueError as exc: raise HTTPException(422,str(exc))
    @router.put('/settings')
    async def settings(value:dict):
        if not device.engine: raise HTTPException(422,'Configure the local broker and pairing first')
        try: return device.engine.save_settings(value)
        except (ValueError,TypeError,ArithmeticError): raise HTTPException(422,'Invalid execution settings')
    @router.post('/command')
    async def command(value:Command):
        try:
            event=device.command(**value.model_dump(exclude_none=True)); device.changed.set(); return event.to_dict()
        except (ValueError,TypeError): raise HTTPException(422,'Invalid command or unavailable local execution; check pairing, settings and tracked trade')
    return router
