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
