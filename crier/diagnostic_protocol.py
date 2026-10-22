"""Bounded observational metadata; never used to authorize or price orders."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .trade_diagnostics import validate_quote


class QuoteObservation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: str = Field(min_length=1, max_length=80)
    quote_timestamp: str = Field(max_length=64)
    bid: str | None = Field(default=None, max_length=40)
    ask: str | None = Field(default=None, max_length=40)
    last: str | None = Field(default=None, max_length=40)

    @model_validator(mode='after')
    def valid_quote(self):
        validate_quote(self.model_dump())
        return self


class DiagnosticObservation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stage: Literal['sender', 'receiver']
    observed_at: str = Field(max_length=64)
    clock_offset_ms: float | None = Field(default=None, allow_inf_nan=False, ge=-604800000, le=604800000)
    clock_uncertainty_ms: float | None = Field(default=None, allow_inf_nan=False, ge=0, le=30000)
    clock_sampled_at: str | None = Field(default=None, max_length=64)
    quote: QuoteObservation | None = None
    quote_error: str | None = Field(default=None, max_length=160)

    @field_validator('observed_at', 'clock_sampled_at')
    @classmethod
    def aware_date(cls, value):
        if value is not None:
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('Timestamp must include timezone')
        return value


class DiagnosticRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: str = Field(max_length=36)
    observation: DiagnosticObservation

    @field_validator('event_id')
    @classmethod
    def canonical_uuid(cls, value):
        if str(UUID(value)) != value:
            raise ValueError('Canonical UUID required')
        return value
