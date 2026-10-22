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
    if not number.is_finite() or number < 0:
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
    delta = second - first
    return dict(status='available', reference=field, sender=str(first),
                receiver=str(second), change=str(delta),
                change_pct=str(delta / first * 100) if first else None)


def trade_report(events, side='buy'):
    """Return an exportable evidence report with explicit missing-data markers."""
    rows = sorted(events, key=lambda event: event['timestamp'])
    quotes = {}
    for event in rows:
        if event['stage'] == 'market_quote_observed':
            stage = event['details']['observation_stage']
            quotes[stage] = event['details']
    sender = quotes.get('sender')
    receiver = quotes.get('receiver')
    comparison = (premium_comparison(sender, receiver, side) if sender and receiver
                  else dict(status='unavailable', reason='sender_or_receiver_quote_missing'))
    return dict(trade_id=rows[0]['trade_id'] if rows else None,
                timeline=rows, quotes=quotes, premium_movement=comparison,
                cross_device_latency_ms=None,
                cross_device_latency_note='Not computed without verified clock synchronization')


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
