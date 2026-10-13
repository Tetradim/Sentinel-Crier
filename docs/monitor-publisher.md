# Running one Crier monitor and publisher

Crier observes fills and publishes messages. It has no trading executor. Existing Sentinel bots can independently consume appropriate alerts. Monitor and publisher components share a durable SQLite store within one application; the console supervises the selected read-only observer as a child process so a blocking SDK cannot freeze the UI.

## Starting the application

The default `python -m crier serve` starts the private web console and receipt inbox, with delivery disabled and no broker selected. Configure environment variables from `.env.example` on the host. The Python CLI reads process environment, not `.env`; Docker Compose loads `.env`.

Select `CRIER_MONITOR=webull` or `tradier`, or use `python -m crier serve --monitor tradier`. Credentials remain on the host. Capture-only observation records private evidence until that adapter's verification requirements are met. Webull also requires the existing enrollment manifest and cumulative-price check. Tradier's first complete validated poll establishes a suppressed baseline. See the broker validation documents before enabling automatic jobs.

Enable publishing only after checking the destination and pending Activity:

```text
DISCORD_WEBHOOK_URL=<your private Discord channel webhook>
CRIER_PUBLISHER_VERIFIED=true
CRIER_DELIVERY_ENABLED=true
```

Restart after changing these settings. This enables automatic delivery of queued jobs, including earlier receipts you confirmed while in preview mode. The UI's Pause delivery switch keeps capture active and holds pending messages. No external posting is required to explore sample studio layouts.

One managed monitor is selected per installation. A separate `watch --monitor webull` or `watch --monitor tradier` process remains supported with `serve --monitor none`; this is an alternative deployment, not a second monitor. Shared OS locks reject simultaneous observers. Observer errors appear in Connections; restart after fixing configuration. Running-process status is distinct from account connectivity.

## Receipt capture for other brokers

Capture inbox accepts pasted text. It is manual evidence capture, not background notification interception, OCR, or broker verification. The optional key/value format prefills the review form:

```text
account: my-stable-account-alias
order_id: original-broker-order-id
symbol: SPY261218C00600000
category: US_OPTION
side: BUY
intent: UNKNOWN
cumulative_qty: 2
average_price: 1.25
occurred_at: 2026-10-13T09:42:18-05:00
status: FILLED
```

Choose the broker slug and sandbox/production scope when saving. For stocks, use a ticker and `US_STOCK`. Options require the full OCC symbol, including expiration year, call/put and strike. Supply the actual timestamp with UTC offset. Unknown intent stays `UNKNOWN`; a buy alone does not prove opening a long position. Quantity is total filled so far for the order and price is the cumulative weighted average, not the most recent execution's price.

Saving creates a pending receipt; it does not enqueue or post. Review all fields and choose **Queue user-confirmed alert**, or reject the receipt. Successful confirmation atomically creates the durable job and resolves the receipt. Repeating confirmation with identical values is safe. Changing a resolved receipt is a conflict; capture new evidence for corrections. Reuse the original order ID and stable account alias so another receipt for the same order can be compared against the existing cumulative watermark.

Public messages identify receipts as **User-confirmed** and their timestamps as **User-supplied time**. The Echo BTO template is refused for receipts. A content-identical receipt in the same broker/environment is deduplicated; two genuinely distinct trades must include their distinct original order IDs. Do not invent missing quantities, prices or IDs to force publication.

The synthetic receipt button only fills the input. If you deliberately confirm it, it becomes a sandbox job. Use a separate data directory for experiments so those jobs cannot later mix with real queued announcements. Studio samples never create jobs.

## Versioned Sentinel event intake

The integration follows Edge/Pulse's shared-key and acknowledgement pattern with a separate read-only fill contract. It does not call Edge/Pulse trading endpoints and is not wire-compatible with their execution instructions.

Set `CRIER_INTAKE_KEY` to a random secret of at least 32 characters, different from the console access token. Leave `CRIER_INTAKE_VERIFIED=false` while building the source mapping. When its scope, baseline behavior, deduplication, quantities, average-price semantics and timestamp provenance have been tested, set it to `true` and restart.

- `GET /api/intake/schema`: authenticated contract discovery; available before verification.
- `POST /api/intake/fills`: accepts a validated cumulative order observation after verification.
- Send `X-API-Key` with the dedicated observer key over HTTPS, or loopback HTTP for local development.
- Optionally send `Idempotency-Key`; it must equal the body `event_id`.

Example body with synthetic data:

```json
{
  "contract_version": "crier.fill.v1",
  "event_id": "my-observer:order-42:revision-2",
  "snapshot": {
    "broker": "mybroker",
    "environment": "sandbox",
    "account": "stable-private-account-id",
    "order_id": "42",
    "symbol": "AAPL",
    "category": "US_STOCK",
    "side": "BUY",
    "intent": "UNKNOWN",
    "cumulative_qty": "3",
    "average_price": "210.25",
    "occurred_at": "2026-10-13T14:42:18Z",
    "status": "FILLED",
    "verification": "broker_reported",
    "time_basis": "execution"
  }
}
```

`time_basis` is `execution`, `order_updated`, or `user_supplied`. Do not substitute receipt arrival time for execution time. The broker slug is a label for a trusted source, not evidence that an adapter exists. Crier cannot verify the truth of data asserted by a configured integration; protecting and validating that observer is part of setup.

The response contains `accepted`, `outcome`, `reference`, `event_id` and `contract_version`. Accepted means durably processed; it does **not** mean Discord delivered the alert. Outcomes include `queued`, `duplicate`, `stale` and `review`. Read Activity for delivery status. An unsupported template or disputed cumulative order can be accepted into review without sending.

On a lost HTTP response, retry the identical event with the same ID. It returns the original acknowledgement without another job. A reused ID with changed data returns HTTP 409. Give genuine later observations/corrections a new event ID; cumulative accounting still deduplicates unchanged fills. Version is required; unknown fields or unsupported versions are rejected. Namespace IDs by observer because this installation has one intake-key trust boundary.

Initial integration observations are not automatically baselined: a previously unseen order's entire reported filled quantity is treated as new. An external observer must suppress pre-start history or establish its own initial capture point before forwarding. This differs from the built-in broker enrollment paths.

## Delivery and recovery

All accepted jobs have a stable public reference and frozen payload. Receipt/account IDs remain private. Broker/environment/account/order scope controls deduplication. Conflicting source values quarantine pending jobs. If the conflict arrives during an HTTP attempt, any later retry is also held; a message already accepted by Discord cannot be unsent retroactively.

Discord has no general idempotency key for webhook posting. Definitive rate limits can retry; an ambiguous send remains `uncertain` for inspection instead of blind retry. The current console displays these states; automated reconciliation or user-facing repair controls are not implemented. Do not clear database records to manufacture a resend.

Neither built-in adapter guarantees gap-free history. Webull has no automatic history backfill; Tradier's endpoint is current-session only and combines fills between polls. One unsupported/malformed Tradier order holds the complete verified poll, including otherwise supported orders. Connections reports failure and private audit evidence is retained. These limits are covered in the validation guides, not hidden behind a green process indicator.

## iPhone and desktop

The responsive browser console works from either device when the service is reachable. An always-on host runs the monitor while the person trades in the ordinary brokerage app. Use HTTPS for remote access. Closing Safari does not stop the host. This implementation does not offer native cross-app notification access, automatic Robinhood monitoring, a native iOS application or a desktop screen watcher.
