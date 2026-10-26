"""Observational copy reports. No value here grants trading permission."""
from datetime import datetime, timezone
from decimal import Decimal, localcontext, ROUND_HALF_UP
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from .diagnostic_protocol import QuoteObservation

Revision = Annotated[int, Field(strict=True, ge=1, le=9007199254740991)]
Units = Annotated[int, Field(strict=True, ge=0, le=1000000)]
State = Literal['received','submitted','working','partially_filled','filled','cancel_pending','canceled','closed','blocked','unknown','not_submitted']
Reason = Literal['broker_unavailable','reconciliation_required','entries_paused','invalid_instruction','not_submitted','quantity_unavailable','expired','clock_uncertain','client_unavailable']


def stamp(value):
    if type(value) is not str or len(value)>64:
        raise ValueError('Invalid observation timestamp')
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None: raise ValueError('Timestamp requires timezone')
    return value


def amount(value):
    if value is None: return None
    if type(value) is not str or len(value)>120 or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?',value):
        raise ValueError('Use a nonnegative plain decimal string')
    significant=value.replace('.','').lstrip('0').rstrip('0')
    if len(significant)>80: raise ValueError('Amount exceeds precision limit')
    return Decimal(value)


class PresenceReport(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    version: Literal[1]=1
    revision: Revision
    observed_at: StrictStr
    platform: Literal['windows','android','ios','python']
    transport: Literal['push','poll','connecting']
    entries_enabled: StrictBool

    @field_validator('version',mode='before')
    @classmethod
    def version_integer(cls,value):
        if type(value) is not int or value!=1: raise ValueError('Invalid report version')
        return value

    @field_validator('observed_at')
    @classmethod
    def aware(cls,value): return stamp(value)


class StatusReport(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    version: Literal[1]=1
    event_id: StrictStr=Field(max_length=36)
    revision: Revision
    observed_at: StrictStr
    broker_observed_at: StrictStr|None=None
    state: State
    target_quantity: Annotated[int,Field(strict=True,ge=0,le=1000)]|None=None
    bought: Units
    sold: Units
    buy_premium: StrictStr|None=None
    sell_premium: StrictStr|None=None
    currency: Literal['USD']|None=None
    multiplier: StrictInt|None=None
    fees: StrictStr|None=None
    quote: QuoteObservation|None=None
    reason: Reason|None=None

    @field_validator('version',mode='before')
    @classmethod
    def version_integer(cls,value):
        return PresenceReport.version_integer(value)

    @field_validator('event_id')
    @classmethod
    def canonical_uuid(cls,value):
        if str(UUID(value))!=value: raise ValueError('Canonical UUID required')
        return value

    @field_validator('observed_at','broker_observed_at')
    @classmethod
    def aware(cls,value): return stamp(value) if value is not None else None

    @field_validator('buy_premium','sell_premium','fees')
    @classmethod
    def money(cls,value):
        amount(value)
        return value

    @model_validator(mode='after')
    def consistent(self):
        if self.sold>self.bought: raise ValueError('Sales exceed tracked purchases')
        for count,text in ((self.bought,self.buy_premium),(self.sold,self.sell_premium)):
            value=amount(text)
            if value is not None and ((count==0 and value!=0) or (count>0 and value<=0)):
                raise ValueError('Premium contradicts cumulative quantity')
        if (self.currency is None)!=(self.multiplier is None) or self.multiplier not in (None,1,100):
            raise ValueError('Incomplete or unsupported instrument metadata')
        if self.fees is not None and self.currency is None: raise ValueError('Fees require currency evidence')
        return self


def validate_status_binding(report,event):
    if report.multiplier is not None and report.multiplier!=(100 if event['asset']=='option' else 1):
        raise ValueError('Multiplier does not match source instrument')


def dashboard_text(snapshot):
    if snapshot is None: return 'Connect as Host or Receive to load the copy dashboard. Status is unavailable until the service supplies evidence.'
    lines=[f"{snapshot['role'].title()} · {snapshot['environment']} · as of {snapshot['generated_at']}",
           'Read-only, device-reported broker evidence. Missing telemetry does not mean a position is closed.']
    if snapshot['truncated']: lines.append('Partial snapshot: rows omitted; no complete portfolio total.')
    now=datetime.now(timezone.utc)
    for member in snapshot['members']:
        presence=member.get('presence') or {}; seen=member.get('last_seen_at')
        try: age=(now-datetime.fromisoformat(stamp(seen).replace('Z','+00:00'))).total_seconds()
        except (ValueError,TypeError): age=None
        health='revoked' if member['revoked'] else 'stale/offline' if age is None or not 0<=age<=45 else f'seen {int(age)}s ago'
        lines.append(f"\n{member['actor']} · {presence.get('platform','unknown platform')} · {presence.get('transport','unknown transport')} · {health}")
    for event in snapshot['events']:
        lines.append(f"\n{event['symbol']} · host {event['action']} {event['quantity']} @ {event['limit_price']} · revision {event['sequence']}")
        rows=[s for s in snapshot['statuses'] if s['report']['event_id']==event['event_id']]
        if not rows: lines.append('Reconciliation status unavailable for this source revision.')
        for row in rows:
            r=StatusReport.model_validate(row['report']).model_dump(); metrics=dashboard_metrics(r)
            show=lambda key: metrics[key] if metrics[key] is not None else 'unavailable'
            lines.extend([f"{row['actor']} · {r['state']} · {r['reason'] or 'no reported block'}",
                f"Local target {r['target_quantity'] if r['target_quantity'] is not None else 'unavailable'} · bought {r['bought']} / sold {r['sold']} / remaining {metrics['remaining']}",
                f"Entry {show('entry_average')} · exit {show('exit_average')} · gross USD {show('gross_realized_pnl')} · net USD {show('net_realized_pnl')}",
                f"Open estimate USD {show('unrealized_estimate')} · broker evidence {r['broker_observed_at'] or 'unavailable'} · reported {row['received_at']}"])
            host=next((s['report'] for s in rows if s['actor']=='host'),None)
            if row['actor']!='host' and host:
                host_metrics=dashboard_metrics(host)
                for key,label in (('entry_average','entry'),('exit_average','exit')):
                    delta=_price(Decimal(metrics[key])-Decimal(host_metrics[key])) if metrics[key] is not None and host_metrics[key] is not None else 'unavailable'
                    lines.append(f'Receiver − host actual {label} premium: {delta} (rounded)')
            from .trade_diagnostics import trade_report
            observations=[dict(timestamp=d['observation']['observed_at'],trade_id=event['trade_id'],event_id=event['event_id'],
                stage='diagnostic_observation',details=dict(actor=d['actor'],observation=d['observation'])) for d in snapshot['diagnostics']
                if d['event_id']==event['event_id'] and d['actor'] in ('host',row['actor'])]
            evidence=trade_report(observations,'sell' if event['action']=='exit' else 'buy')
            if row['actor']!='host':
                latency=evidence['cross_device_latency_ms']; uncertainty=evidence['clock_uncertainty_ms']
                lines.append(f'Estimated delivery {latency:.1f} ms ± {uncertainty:.1f} ms' if latency is not None else 'Delivery estimate unavailable: matching clock evidence required')
                movement=evidence['premium_movement']
                lines.append('Near-event quote change: '+str(movement.get('change','unavailable')))
    return '\n'.join(lines)


def _price(value):
    if value is None: return None
    text=format(value.quantize(Decimal('0.00000001'),rounding=ROUND_HALF_UP),'f')
    return text.rstrip('0').rstrip('.') or '0'


def _usd(value):
    if value is None:return None
    rounded=value.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
    return '0.00' if rounded==0 else format(rounded,'f')


def dashboard_metrics(report,as_of=None):
    """Display-only arithmetic; partial realized lot basis is intentionally absent."""
    bought,sold=report['bought'],report['sold']
    if type(bought) is not int or type(sold) is not int or not 0<=sold<=bought<=1000000:
        raise ValueError('Invalid report quantities')
    buy,sell,fees=(amount(report.get(k)) for k in ('buy_premium','sell_premium','fees'))
    multiplier=report.get('multiplier')
    verified=report.get('currency')=='USD' and type(multiplier) is int and multiplier in (1,100)
    with localcontext() as context:
        context.prec=256
        entry=buy/bought if buy is not None and bought else None
        exit=sell/sold if sell is not None and sold else None
        gross=(sell-buy)*multiplier if verified and bought==sold and bought>0 and buy is not None and sell is not None else None
        net=gross-fees if gross is not None and fees is not None else None
        estimate=None
        quote=report.get('quote')
        if bought>sold and verified and entry is not None and quote:
            try:
                normalized=QuoteObservation.model_validate(quote)
                now=datetime.fromisoformat(stamp(as_of).replace('Z','+00:00')) if as_of else datetime.now(timezone.utc)
                seen=datetime.fromisoformat(normalized.quote_timestamp.replace('Z','+00:00'))
                age=(now-seen).total_seconds()
                if 0<=age<=5 and normalized.bid is not None:
                    estimate=(Decimal(normalized.bid)-entry)*(bought-sold)*multiplier
            except (ValueError,TypeError,ArithmeticError): pass
        return dict(remaining=bought-sold,entry_average=_price(entry),exit_average=_price(exit),
                    gross_realized_pnl=_usd(gross),net_realized_pnl=_usd(net),unrealized_estimate=_usd(estimate))
