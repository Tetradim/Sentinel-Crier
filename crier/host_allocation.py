"""Non-executing host-allocation reference arithmetic.

Inputs must eventually come from a verified account coordinator and ownership
ledger. A preview is neither broker evidence nor permission to submit an order.
spendable_cash is coordinator-derived: do not blindly subtract broker-reflected
working orders or held positions twice. No adapter/engine imports this module.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext, ROUND_DOWN, Inexact
import re


def _text(value, name):
    if not isinstance(value,str) or not 1 <= len(value) <= 128 or any(ord(c)<33 or ord(c)>126 for c in value):
        raise ValueError("Invalid "+name)
    return value


def _amount(value):
    if not isinstance(value,str) or len(value)>24 or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?",value):
        raise ValueError("Amounts require canonical nonnegative decimal strings")
    amount=Decimal(value)
    if not amount.is_finite(): raise ValueError("Nonfinite amount")
    return amount


def _count(value,maximum=1000000000):
    if type(value) is not int or not 0 <= value <= maximum: raise ValueError("Invalid unit count")
    return value


def _format(value):
    result=format(value,"f")
    return result.rstrip("0").rstrip(".") if "." in result else result


@dataclass(frozen=True)
class Scope:
    broker: str
    account: str
    environment: str
    def __post_init__(self):
        _text(self.account,"account")
        if not isinstance(self.broker,str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}",self.broker): raise ValueError("Invalid broker identity")
        if self.environment not in ("paper","live"): raise ValueError("Invalid environment")


@dataclass(frozen=True)
class Funds:
    scope: Scope
    equity: str
    spendable_cash: str
    observed_at: datetime
    revision: str
    currency: str


@dataclass(frozen=True)
class Usage:
    scope: Scope
    host_id: str
    units: int
    notional: str
    asset: str


@dataclass(frozen=True)
class Allocation:
    mode: str
    value: str
    def amount(self):
        value=_amount(self.value)
        if self.mode not in ("units","dollars","equity_percent"): raise ValueError("Unknown allocation mode")
        if self.mode=="units" and (not re.fullmatch(r"0|[1-9][0-9]*",self.value) or value>1000000000): raise ValueError("Units must be bounded whole units")
        if self.mode=="equity_percent" and value>100: raise ValueError("Percentage exceeds account equity")
        return value


def _aware(value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Account timestamps require timezone")


def preview(*,scope,host_id,funds,usage,pool,sizing,asset,multiplier,buy_limit,
            fee_reserve,max_units,now,allow_downsize=False):
    """Compute one preview against a reusable pool; never changes exposure.

    Usage includes held and pending/unknown exposure, including pending exits
    until confirmed. Pool reductions never request liquidation. Percentages are
    percentages of destination equity, not host equity or stop-loss risk.
    """
    if not isinstance(scope,Scope) or not isinstance(funds,Funds) or not isinstance(usage,Usage): raise ValueError("Explicit account scope and ledger usage required")
    if not isinstance(funds.scope,Scope) or not isinstance(usage.scope,Scope): raise ValueError("Unscoped account inputs")
    _text(host_id,"host");_text(usage.host_id,"usage host");_text(funds.revision,"snapshot revision")
    _aware(now);_aware(funds.observed_at)
    _count(usage.units);_count(max_units,1000)
    if max_units==0 or type(allow_downsize) is not bool: raise ValueError("Invalid admission controls")
    if not isinstance(pool,Allocation) or not isinstance(sizing,Allocation): raise ValueError("Explicit allocations required")
    equity=_amount(funds.equity);cash=_amount(funds.spendable_cash)
    committed=_amount(usage.notional);fee=_amount(fee_reserve)
    pool_value=pool.amount();size_value=sizing.amount()
    result=dict(version=1,preview_only=True,decision="blocked",reason="account_scope_mismatch",target_units=0,
                requested_units=0,reserved_notional=None,remaining_pool=None,snapshot_revision=funds.revision)
    if funds.scope!=scope or usage.scope!=scope or usage.host_id!=host_id:return result
    if funds.currency!="USD":return dict(result,reason="unsupported_currency")
    if usage.asset!=asset:return dict(result,reason="asset_pool_mismatch")
    age=(now-funds.observed_at).total_seconds()
    if not 0<=age<=10 or equity<=0:
        return dict(result,reason="account_snapshot_unavailable")
    if asset not in ("stock","option") or type(multiplier) is not int or multiplier!=(100 if asset=="option" else 1):
        return dict(result,reason="unsupported_instrument")
    if buy_limit is None:return dict(result,reason="bounded_price_required")
    price=_amount(buy_limit)
    if price<=0:raise ValueError("Positive final buy limit required")
    with localcontext() as context:
        context.prec=80;context.traps[Inexact]=True
        unit=price*multiplier
        def monetary(config,value):
            if config.mode=="equity_percent":
                # A fractional cent is never rounded up into spending authority.
                with localcontext() as rounding:
                    rounding.traps[Inexact]=False
                    return (equity*value/100).quantize(Decimal("0.01"),rounding=ROUND_DOWN)
            return value
        if pool.mode=="units":
            remaining=max(0,int(pool_value)-usage.units)
            units_capacity=remaining
            capacity=min(cash,equity)
            remaining_text=remaining
        else:
            remaining=max(Decimal(0),monetary(pool,pool_value)-committed)
            capacity=min(cash,equity,remaining)
            units_capacity=1000000000
            remaining_text=_format(remaining)
        if sizing.mode=="units":requested=int(size_value)
        else:requested=int(max(Decimal(0),monetary(sizing,size_value)-fee)//unit)
        result.update(requested_units=requested,remaining_pool=remaining_text)
        if requested<1:return dict(result,decision="skip",reason="below_one_unit")
        affordable=int(max(Decimal(0),capacity-fee)//unit)
        fitted=min(requested,units_capacity,affordable,max_units)
        if fitted<requested and not allow_downsize:
            return dict(result,decision="skip",reason="allocation_capacity")
        if fitted<1:return dict(result,decision="skip",reason="allocation_capacity")
        return dict(result,decision="eligible",reason="downsized" if fitted<requested else "within_allocation",
                    target_units=fitted,reserved_notional=_format(fitted*unit+fee))
