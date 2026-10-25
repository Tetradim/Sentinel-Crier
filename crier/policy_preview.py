"""Non-executing H.5 reference arithmetic. Never import this as a trade permission."""
from dataclasses import dataclass
from decimal import Decimal, localcontext
import re


def _integer(value, name, low=0, high=1000):
    if type(value) is not int or not low<=value<=high:
        raise ValueError('Invalid '+name)
    return value


def _money(value, name):
    if not isinstance(value,str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?',value) or len(value.replace('.',''))>20:
        raise ValueError('Invalid '+name)
    amount=Decimal(value)
    if amount<=0:
        raise ValueError('Invalid '+name)
    return amount


def _text(amount):
    if amount is None:
        return None
    value=format(amount,'f')
    return value.rstrip('0').rstrip('.') if '.' in value else value


@dataclass(frozen=True)
class SizingPolicy:
    version: int = 1
    mode: str = 'source'
    fixed_quantity: int | None = None
    ratio_bps: int | None = None
    budget: str | None = None
    max_source_quantity: int = 1000
    max_local_quantity: int = 1000
    max_entry_notional: str | None = None

    def __post_init__(self):
        if type(self.version) is not int or self.version!=1 or self.mode not in ('source','fixed','ratio','budget'):
            raise ValueError('Invalid policy version or mode')
        _integer(self.max_source_quantity,'source cap',1)
        _integer(self.max_local_quantity,'local cap',1)
        for mode, field in (('fixed','fixed_quantity'),('ratio','ratio_bps'),('budget','budget')):
            value=getattr(self,field)
            if self.mode!=mode and value is not None:
                raise ValueError('Unused '+field)
            if self.mode==mode:
                if mode=='budget': _money(value,'budget')
                else: _integer(value,field,1,10000 if mode=='ratio' else 1000)
        if self.max_entry_notional is not None:
            _money(self.max_entry_notional,'notional cap')

    @classmethod
    def from_legacy(cls,settings):
        """Project a legacy cap for review, without changing or saving settings."""
        cap=settings.get('max_quantity',1000)
        return cls(max_source_quantity=cap,max_local_quantity=cap)


def _entry(decision,reason,quantity=0,notional=None):
    return dict(preview_only=True,decision=decision,reason=reason,target_quantity=quantity,estimated_notional=_text(notional))


def preview_entry(*,source_quantity,asset,limit_price=None,contract_size=None,policy=None):
    """Preview a total target for a first entry; not a remaining-order planner."""
    _integer(source_quantity,'source quantity',1)
    if asset not in ('stock','option'):
        raise ValueError('Unsupported asset')
    if policy is not None and not isinstance(policy,dict):
        raise ValueError('Policy must be an explicit mapping')
    sizing=SizingPolicy(**(policy or {}))
    price=_money(limit_price,'final buy limit') if limit_price is not None else None
    if contract_size is not None:
        _integer(contract_size,'contract size',1,100000)
    if source_quantity>sizing.max_source_quantity:
        return _entry('skip','source_quantity_cap')
    if asset=='option' and contract_size is None:
        return _entry('blocked','contract_size_unverified')
    multiplier=1 if asset=='stock' and contract_size is None else contract_size
    if multiplier!=(100 if asset=='option' else 1):
        return _entry('blocked','unsupported_contract_size')
    if price is None and (sizing.mode=='budget' or sizing.max_entry_notional is not None):
        return _entry('blocked','valuation_unavailable')
    with localcontext() as context:
        context.prec=80
        unit=price*multiplier if price is not None else None
        quantity=source_quantity
        if sizing.mode=='fixed': quantity=sizing.fixed_quantity
        elif sizing.mode=='ratio': quantity=source_quantity*sizing.ratio_bps//10000
        elif sizing.mode=='budget': quantity=int(_money(sizing.budget,'budget')//unit)
        if quantity<1:
            return _entry('skip','below_one_unit')
        if quantity>sizing.max_local_quantity:
            return _entry('skip','local_quantity_cap')
        notional=unit*quantity if unit is not None else None
        if sizing.max_entry_notional is not None and notional>_money(sizing.max_entry_notional,'notional cap'):
            return _entry('skip','entry_notional_cap',notional=notional)
        return _entry('eligible','calculated',quantity,notional)


def _exit(decision,reason,quantity=0):
    return dict(preview_only=True,decision=decision,reason=reason,quantity=quantity)


def preview_exit(*,requested_quantity,bought,sold,available,reconciled=False,mode='requested',sold_for_instruction=0,source_entry_quantity=None,source_exit_cumulative=None):
    """Preview arithmetic only. Caller-supplied reconciliation is not authorization."""
    if type(reconciled) is not bool or mode not in ('requested','proportional','close_tracked'):
        raise ValueError('Invalid exit policy or reconciliation marker')
    _integer(requested_quantity,'requested quantity',1)
    _integer(bought,'tracked purchases'); _integer(sold,'tracked sales')
    _integer(sold_for_instruction,'instruction sales')
    if available is not None:
        _integer(available,'available holdings',0,1000000000)
    if sold>bought or sold_for_instruction>sold or (mode=='requested' and sold_for_instruction>requested_quantity):
        return _exit('blocked','inconsistent_journal')
    if not reconciled:
        return _exit('blocked','reconciliation_required')
    if available is None:
        return _exit('blocked','availability_unavailable')
    remaining=bought-sold
    if remaining==0:
        return _exit('skip','no_tracked_holdings')
    if mode=='proportional':
        _integer(source_entry_quantity,'source entry quantity',1)
        _integer(source_exit_cumulative,'source cumulative exits')
        if source_exit_cumulative>source_entry_quantity:
            return _exit('blocked','source_exit_inconsistent')
        due=max(0,bought*source_exit_cumulative//source_entry_quantity-sold)
    elif mode=='close_tracked':
        due=remaining
    else:
        due=max(0,requested_quantity-sold_for_instruction)
    if due==0:
        return _exit('skip','nothing_due')
    if available==0:
        return _exit('blocked','holdings_unavailable')
    return _exit('eligible','calculated',min(due,remaining,available))
