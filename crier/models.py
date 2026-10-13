from datetime import date, datetime
from decimal import Decimal
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OCC = re.compile(r"([A-Z]{1,6})\s*(\d{6})([CP])(\d{8})")


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = "Your trades"
    format: Literal["homebrew", "card", "text", "echo"] = "homebrew"
    color: str = "#62d9ad"
    timezone: str = "America/Chicago"
    show_quantity: bool = True
    show_time: bool = True
    paused: bool = False

    @field_validator("display_name")
    @classmethod
    def safe_name(cls, value):
        if not re.fullmatch(r"[\w .'-]{1,40}", value, flags=re.ASCII):
            raise ValueError("Use 1–40 letters, numbers, spaces, periods, apostrophes or hyphens")
        return value

    @field_validator("color")
    @classmethod
    def valid_color(cls, value):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value): raise ValueError("Use a hex color")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try: ZoneInfo(value)
        except ZoneInfoNotFoundError: raise ValueError("Unknown IANA timezone")
        return value


class Snapshot(BaseModel):
    """One order's cumulative execution quantity and weighted average price."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    broker: str = Field(default="webull", pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    environment: Literal["sandbox", "production"] = "sandbox"
    account: str = Field(min_length=1, max_length=100)
    order_id: str = Field(min_length=1, max_length=100)
    symbol: str = Field(max_length=32)
    category: Literal["US_STOCK", "US_OPTION"]
    side: Literal["BUY", "SELL"]
    intent: Literal["OPEN", "CLOSE", "UNKNOWN"] = "UNKNOWN"
    cumulative_qty: Decimal = Field(gt=0, allow_inf_nan=False, max_digits=20, decimal_places=8)
    average_price: Decimal = Field(gt=0, allow_inf_nan=False, max_digits=20, decimal_places=8)
    occurred_at: datetime
    status: Literal["PARTIAL", "FILLED"]
    verification: Literal["broker_reported", "user_confirmed"] = "broker_reported"
    time_basis: Literal["execution", "order_updated", "user_supplied"] = "execution"

    @field_validator("account", "order_id")
    @classmethod
    def nonempty_identity(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Identity must be nonempty and contain no control characters")
        return value

    @field_validator("symbol")
    @classmethod
    def canonical_symbol(cls, value):
        match = OCC.fullmatch(value)
        return "".join(match.groups()) if match else value

    @model_validator(mode="after")
    def validate_contract(self):
        if self.occurred_at.tzinfo is None: raise ValueError("Fill timestamp must include timezone")
        if self.category == "US_OPTION":
            match = OCC.fullmatch(self.symbol)
            if not match: raise ValueError("Options require a full OCC symbol; multi-leg orders are unsupported")
            stamp = match[2]
            date(2000 + int(stamp[:2]), int(stamp[2:4]), int(stamp[4:]))
            if int(match[4]) <= 0: raise ValueError("Option strike must be positive")
            if self.cumulative_qty != self.cumulative_qty.to_integral_value():
                raise ValueError("Option quantity must be whole contracts")
        elif not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", self.symbol):
            raise ValueError("Invalid stock symbol")
        return self

    @property
    def contract(self):
        if self.category == "US_STOCK": return self.symbol
        m = OCC.fullmatch(self.symbol)
        return f"{m[1]} ${number(Decimal(m[4]) / 1000)}{m[3]}"

    @property
    def expiration(self):
        if self.category == "US_STOCK": return None
        s = OCC.fullmatch(self.symbol)[2]
        return f"20{s[:2]}-{s[2:4]}-{s[4:]}"


def number(value):
    return format(Decimal(str(value)), "f").rstrip("0").rstrip(".") if "." in format(Decimal(str(value)), "f") else format(Decimal(str(value)), "f")
