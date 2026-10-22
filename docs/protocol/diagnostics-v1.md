# Optional diagnostics transport

Diagnostics accompany intent protocol v1 without changing its order payload.
They never authorize, price, delay, or acknowledge execution. Older clients and
relays can continue exchanging orders without this extension; unsupported
diagnostic endpoints leave measurements unavailable.

## Authentication and scope

All endpoints use the existing pairing bearer credential. No broker keys are
sent to the relay. Revoked credentials are rejected. Every observation belongs
to an existing event in the authenticated channel. Receivers cannot access
events preceding their join cursor.

Each event has one immutable observation per device credential. A host writes
the `sender` stage; a receiver writes `receiver`. A receiver can read its own
observation and the host's. Hosts read their own observation, and cannot use
this endpoint to list receivers' evidence. Identical POST retries are safe;
changed evidence for the same event/device returns 409.

## Clock probe

`GET /api/sync/clock` returns `{"server_time_ms": 1790000000000.0}` with
`Cache-Control: no-store`. The value is the relay's Unix time in milliseconds.

Clients measure both local wall time and monotonic elapsed time around the
request. Offset is server time minus the local wall-clock midpoint. Half the
round-trip duration is the uncertainty estimate. Reject samples when wall and
monotonic elapsed time differ by more than 100 ms; use samples for at most
60 seconds. This is an estimate based on a stable relay clock and network
round-trip bounds, not a guarantee of sub-millisecond synchronization.

## Evidence exchange

`POST /api/sync/diagnostics` accepts:

```json
{
  "event_id": "00000000-0000-4000-8000-000000000001",
  "observation": {
    "stage": "sender",
    "observed_at": "2026-10-21T15:00:00Z",
    "clock_offset_ms": 12.0,
    "clock_uncertainty_ms": 8.0,
    "clock_sampled_at": "2026-10-21T14:59:50Z",
    "quote": {
      "source": "alpaca:opra",
      "quote_timestamp": "2026-10-21T15:00:00Z",
      "bid": "0.19",
      "ask": "0.20",
      "last": null
    },
    "quote_error": null
  }
}
```

Missing clock fields and quotes are null. All timestamps require a timezone.
Quote prices are finite, nonnegative decimal strings. Clock values must be
finite; uncertainty cannot be negative. Unknown fields and oversized requests
are rejected. An event not yet published returns 404; clients retry separately
from the order outbox. Diagnostic failures never block order delivery.

`GET /api/sync/diagnostics?event_id=...` returns:

```json
{"observations": [{"actor": "host", "observation": {"stage": "sender"}}]}
```

The abbreviated observation above is the full stored object in actual responses.
Receiver actor IDs are opaque. Trade symbol, side and revision come from the
immutable intent associated with the event ID, not from an independently supplied
diagnostic identity.

## Comparisons

Capture snapshots asynchronously near an event. A snapshot is not the exact price
at the order button and is not a fill. Compare the same event and the same source:
ask-to-ask for buys, bid-to-bid for sells. Reject missing, stale, indicative, or
invalid evidence. Capture uses explicit `iex` for stocks and `opra` for options;
there is no fallback to indicative options quotes. The IEX source is a limited
market view and must retain its source label.

Receiver latency is `(receiver observed_at + receiver offset) - (sender
observed_at + sender offset)`. Display the sum of both uncertainty estimates.
Missing or stale samples make latency unavailable. A negative estimate outside
the uncertainty range is inconsistent evidence, not a valid latency. This
measures instruction delivery, not order acceptance or fill time.

Provider reference: [Alpaca latest option quotes](https://docs.alpaca.markets/us/reference/optionlatestquotes).
