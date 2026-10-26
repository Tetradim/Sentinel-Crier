"""Validated local execution policy; these calculations never authorize a POST."""
from dataclasses import dataclass, asdict
from decimal import Decimal, localcontext, ROUND_DOWN, ROUND_UP, Inexact
from .policy_preview import SizingPolicy, preview_entry


@dataclass(frozen=True)
class ExecutionPolicy(SizingPolicy):
    exit_mode: str = 'requested'
    entry_timeout_seconds: int | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.exit_mode not in ('requested', 'proportional', 'close_tracked'):
            raise ValueError('Invalid exit policy')
        seconds = self.entry_timeout_seconds
        if seconds is not None and (type(seconds) is not int or not 1 <= seconds <= 86400):
            raise ValueError('Invalid entry timeout')

    @classmethod
    def parse(cls, value):
        if type(value) is not dict:
            raise ValueError('Policy must be an explicit mapping')
        try:
            return cls(**value)
        except TypeError as exc:
            raise ValueError('Unknown execution policy field') from exc

    def sizing(self):
        return {k: v for k, v in asdict(self).items()
                if k not in ('exit_mode', 'entry_timeout_seconds')}


def exact_cost(left, right, *, multiply=False):
    """Broker evidence may exceed policy input precision; never round spending."""
    with localcontext() as context:
        context.prec=80
        context.traps[Inexact]=True
        return left*right if multiply else left+right


def validate_metadata(value, event, account):
    expected = dict(account=account, environment=event['environment'],
                    symbol=event['symbol'], asset=event['asset'], currency='USD',
                    multiplier=100 if event['asset'] == 'option' else 1)
    if type(value) is not dict or value != expected or type(value.get('multiplier')) is not int:
        raise ValueError('Unverified policy instrument/account metadata')
    return expected


def final_limit(event, pricing, side='buy'):
    if set(pricing)!={'mode','max_slippage_bps','max_slippage_amount'}:
        raise ValueError('Invalid saved pricing basis')
    if pricing['mode'] not in ('exact_limit','bounded_limit','market') or type(pricing['max_slippage_bps']) is not int or not 0<=pricing['max_slippage_bps']<=10000:
        raise ValueError('Invalid saved pricing basis')
    if type(pricing['max_slippage_amount']) is not str: raise ValueError('Invalid saved slippage')
    amount=Decimal(pricing['max_slippage_amount'])
    if not amount.is_finite() or amount<0: raise ValueError('Invalid saved slippage')
    if pricing['mode']=='market': return None
    price=Decimal(event['limit_price'])
    if pricing['mode']=='bounded_limit':
        delta=min(price*Decimal(pricing['max_slippage_bps'])/10000,amount)
        price=price+delta if side=='buy' else price-delta
    tick=Decimal('0.01') if price>=1 or event['asset']=='option' else Decimal('0.0001')
    price=price.quantize(tick,rounding=ROUND_DOWN if side=='buy' else ROUND_UP)
    if price<=0: raise ValueError('Nonpositive bounded price')
    return str(price)


def entry_target(policy, event, limit, metadata, bought=0, spent=Decimal(0)):
    """Freeze a revision target using verified cumulative buys, never net holdings."""
    with localcontext() as context:
        context.prec = 80
        context.traps[Inexact] = True
        if policy.mode == 'budget' and bought:
            if limit is None:
                raise ValueError('Budget requires a limit')
            remaining = max(Decimal(0), Decimal(policy.budget) - spent)
            target = int(bought) + int(remaining // (Decimal(limit) * metadata['multiplier']))
            if event['quantity'] > policy.max_source_quantity or target > policy.max_local_quantity:
                raise ValueError('Policy quantity cap')
        else:
            sizing=dict(policy.sizing(),max_entry_notional=None)
            result = preview_entry(source_quantity=event['quantity'], asset=event['asset'],
                                   limit_price=limit, contract_size=metadata['multiplier'],
                                   policy=sizing)
            if result['decision'] != 'eligible':
                raise ValueError(result['reason'])
            target = result['target_quantity']
        due = max(0, target - int(bought))
        if policy.max_entry_notional is not None:
            if limit is None or spent + due * Decimal(limit) * metadata['multiplier'] > Decimal(policy.max_entry_notional):
                raise ValueError('Entry notional cap')
        return target


def source_exit_fraction(events, desired):
    """Require a complete, immutable, identity-consistent source intent history."""
    ordered = sorted(events, key=lambda e: e['sequence'])
    if len(ordered) != desired['sequence'] or [e['sequence'] for e in ordered] != list(range(1, desired['sequence'] + 1)):
        raise ValueError('Incomplete source intent history')
    if not ordered or ordered[0]['action'] != 'enter' or ordered[-1] != desired:
        raise ValueError('Invalid source intent history')
    denominator = None
    exits = 0
    invalidated = False
    for event in ordered:
        if any(event[k] != desired[k] for k in ('trade_id', 'environment', 'asset', 'symbol')):
            raise ValueError('Source identity changed')
        if event['action'] in ('enter', 'replace'):
            if invalidated or (event['action'] == 'enter' and event['sequence'] != 1):
                raise ValueError('Source entry after invalidation')
            denominator = event['quantity']
        else:
            invalidated = True
            if event['action'] == 'exit':
                exits += event['quantity']
    if denominator is None:
        raise ValueError('Missing source entry')
    return min(exits, denominator), denominator
