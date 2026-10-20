"""Versioned wire contract shared by the three native execution clients."""
from datetime import date, datetime
from decimal import Decimal
import re
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .models import OCC

class IntentEvent(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    version: Literal[1] = 1
    event_id: str
    trade_id: str
    sequence: int = Field(strict=True, ge=1, le=2147483647)
    action: Literal['enter','replace','cancel','exit']
    environment: Literal['paper','live']
    symbol: str = Field(max_length=32)
    asset: Literal['stock','option']
    quantity: int = Field(strict=True, ge=1, le=1000)
    limit_price: Decimal = Field(gt=0, le=100000, allow_inf_nan=False, max_digits=14, decimal_places=8)
    created_at: datetime
    expires_at: datetime

    @field_validator('event_id','trade_id')
    @classmethod
    def uuid(cls,value):
        if str(UUID(value)) != value: raise ValueError('Use canonical lowercase UUID')
        return value

    @model_validator(mode='after')
    def validate_event(self):
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError('Timestamps must include timezone')
        duration=(self.expires_at-self.created_at).total_seconds()
        if duration <= 0 or (self.action in ('enter','replace') and duration > 30):
            raise ValueError('Entry instructions require a lifetime of at most 30 seconds')
        if self.asset=='option':
            match=OCC.fullmatch(self.symbol)
            if not match or ' ' in self.symbol: raise ValueError('Use canonical OCC option symbol')
            stamp=match[2]; date(2000+int(stamp[:2]),int(stamp[2:4]),int(stamp[4:]))
            if int(match[4])<=0: raise ValueError('Invalid option strike')
        elif not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,9}',self.symbol): raise ValueError('Invalid stock symbol')
        return self

    def to_dict(self): return self.model_dump(mode='json')
