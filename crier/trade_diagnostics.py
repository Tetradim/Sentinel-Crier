"""Trade diagnostics from observed events, not inferred market prices.

Quotes are optional and must be supplied by an actual market-data provider.
Never interpret an order limit as an observed bid/ask or fill.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import csv
import io


def _decimal(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Invalid quote price')
    if not number.is_finite() or number < 0 or number > Decimal('1e12'):
        raise ValueError('Invalid quote price')
    return number


def validate_quote(quote):
    """Require provenance and a source timestamp for each real quote."""
    if not isinstance(quote, dict) or not isinstance(quote.get('source'), str) or not quote['source'].strip():
        raise ValueError('Quote source required')
    try:
        timestamp = datetime.fromisoformat(quote['quote_timestamp'].replace('Z', '+00:00'))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError('Valid quote timestamp required') from exc
    if timestamp.tzinfo is None:
        raise ValueError('Quote timestamp must include timezone')
    bid = _decimal(quote.get('bid'))
    ask = _decimal(quote.get('ask'))
    last = _decimal(quote.get('last'))
    if bid is None and ask is None and last is None:
        raise ValueError('At least one observed price required')
    if bid is not None and ask is not None and ask < bid:
        raise ValueError('Crossed quote is not suitable for comparison')
    return dict(source=quote['source'], quote_timestamp=timestamp.astimezone(timezone.utc).isoformat(),
                bid=str(bid) if bid is not None else None,
                ask=str(ask) if ask is not None else None,
                last=str(last) if last is not None else None,
                midpoint=str((bid + ask) / 2) if bid is not None and ask is not None else None)


def premium_comparison(sender, receiver, side='buy'):
    """Compare like-for-like observed executable sides; never fabricate quotes."""
    if side not in ('buy', 'sell'):
        raise ValueError('Invalid side')
    field = 'ask' if side == 'buy' else 'bid'
    first, second = sender.get(field), receiver.get(field)
    if first is None or second is None:
        return dict(status='unavailable', reason='missing_'+field)
    first, second = Decimal(first), Decimal(second)
    if first <= 0 or second <= 0:
        return dict(status='unavailable', reason='no_executable_'+field)
    delta = second - first
    return dict(status='available', reference=field, sender=str(first),
                receiver=str(second), change=str(delta),
                change_pct=str(delta / first * 100) if first else None)


def _millis(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Timezone required')
    return stamp.timestamp() * 1000


def _latency(sender, receiver):
    import math
    try:
        corrected = []
        uncertainties = []
        for observation in (sender, receiver):
            observed = _millis(observation['observed_at'])
            sampled = _millis(observation['clock_sampled_at'])
            offset = observation['clock_offset_ms']
            uncertainty = observation['clock_uncertainty_ms']
            if any(isinstance(x, bool) or not isinstance(x, (int,float)) or not math.isfinite(x) for x in (offset,uncertainty)):
                raise ValueError('Invalid clock')
            if not 0 <= observed-sampled <= 60000 or not 0 <= uncertainty <= 30000 or abs(offset) > 604800000:
                raise ValueError('Stale clock')
            corrected.append(observed+offset)
            uncertainties.append(uncertainty)
        value = corrected[1]-corrected[0]
        uncertainty = sum(uncertainties)
        if value < -uncertainty:
            raise ValueError('Impossible latency')
        return value, uncertainty
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError):
        return None, None


def _fresh_quote(observation):
    try:
        if observation.get('quote_error') is not None or _latency(observation, observation)[0] is None:
            return None
        quote = validate_quote(observation['quote'])
        if quote['source'] not in ('alpaca:iex', 'alpaca:opra'):
            return None
        observed = _millis(observation['observed_at']) + (observation.get('clock_offset_ms') or 0)
        if abs(observed-_millis(quote['quote_timestamp'])) > 5000:
            return None
        return quote
    except (KeyError,TypeError,ValueError,AttributeError):
        return None


def trade_report(events, side='buy'):
    """Compare only evidence for the same immutable event and quote feed."""
    rows = sorted(events, key=lambda event: event['timestamp'])
    grouped = {}
    for row in rows:
        event_id = row.get('event_id') or row.get('details',{}).get('event_id')
        if event_id:
            group = grouped.setdefault(event_id, {'event_id':event_id,'observations':{},'sequence':0})
            group['sequence'] = max(group['sequence'],row.get('details',{}).get('sequence',0))
            if row['stage']=='market_quote_observed' and row['details'].get('observation_stage') in ('sender','receiver'):
                detail=row['details']
                stage=detail['observation_stage']
                group['observations']['host' if stage=='sender' else 'local']=dict(stage=stage,observed_at=row['timestamp'],quote=detail)
            if row['stage']=='diagnostic_observation':
                detail = row['details']
                if isinstance(detail.get('actor'),str) and isinstance(detail.get('observation'),dict):
                    group['observations'][detail['actor']] = detail['observation']
    reports=[]
    for group in grouped.values():
        observations=group['observations']
        sender=observations.get('host')
        receivers={key:value for key,value in observations.items() if value.get('stage')=='receiver' and key!='local'}
        if not receivers and 'local' in observations:
            receivers={'local':observations['local']}
        comparisons=[]
        for actor,receiver in receivers.items():
            first=_fresh_quote(sender) if sender else None
            second=_fresh_quote(receiver)
            comparison=premium_comparison(first,second,side) if first and second and first['source']==second['source'] else dict(status='unavailable',reason='matching_fresh_quotes_missing')
            latency,uncertainty=_latency(sender,receiver) if sender else (None,None)
            comparisons.append(dict(actor=actor,premium_movement=comparison,cross_device_latency_ms=latency,clock_uncertainty_ms=uncertainty,quotes=dict(sender=first,receiver=second)))
        selected=comparisons[0] if comparisons else dict(premium_movement=dict(status='unavailable',reason='sender_or_receiver_quote_missing'),cross_device_latency_ms=None,clock_uncertainty_ms=None,quotes={})
        reports.append(dict(group,receivers=comparisons,**{k:v for k,v in selected.items() if k!='actor'}))
    latest=max(reports,key=lambda x:x['sequence']) if reports else {}
    return dict(trade_id=rows[0]['trade_id'] if rows else None,timeline=rows,events=reports,
                latest_event_id=latest.get('event_id'),quotes=latest.get('quotes',{}),
                premium_movement=latest.get('premium_movement',dict(status='unavailable',reason='sender_or_receiver_quote_missing')),
                cross_device_latency_ms=latest.get('cross_device_latency_ms'),
                clock_uncertainty_ms=latest.get('clock_uncertainty_ms'),
                cross_device_latency_note='Clock-corrected estimate; uncertainty is the sum of clock sample half RTTs' if latest.get('cross_device_latency_ms') is not None else 'Unavailable: matching recent clock samples required')


def export_trade_json(report):
    """Portable UTF-8 JSON evidence bundle."""
    return json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False)+'\n'


def export_trade_csv(report):
    """One row per observed event; details preserved as JSON, not flattened away."""
    stream=io.StringIO(newline='')
    writer=csv.writer(stream)
    writer.writerow(('timestamp_utc','trade_id','event_id','stage','monotonic_ns','details_json'))
    for entry in report['timeline']:
        # Prefix spreadsheet formula characters to prevent CSV formula execution.
        def safe(value):
            value='' if value is None else str(value)
            return "'" + value if value.startswith(('=','+','-','@','\t','\r','\n')) else value
        writer.writerow((safe(entry.get('timestamp')),safe(entry.get('trade_id')),
                         safe(entry.get('event_id')),safe(entry.get('stage')),
                         safe(entry.get('monotonic_ns')),
                         safe(json.dumps(entry.get('details',{}),sort_keys=True))))
    return stream.getvalue()
