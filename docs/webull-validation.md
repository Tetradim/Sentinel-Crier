# Webull validation and enrollment

This is a free self-hosted tool. Each operator connects their own authorized account. No paid tier, Tetradim account system or shared customer credential store is included.

## What must be established

1. API eligibility for the user's region and account; this adapter currently supports US endpoints only.
2. Whether orders entered manually in Webull's iPhone app appear in the account event stream and order queries. The public subscription documentation does not explicitly guarantee this.
3. Whether `filled_qty` is cumulative and `filled_price` is its weighted average for that feed. Crier computes incremental price as `(new_qty * new_average - old_qty * old_average) / incremental_qty`. Last-execution prices cannot be substituted for averages.
4. Stock and option payload shape. Options must supply an unambiguous OCC symbol. Events lacking complete contract data or containing multi-leg information are quarantined. No option contract is guessed from a ticker alone.
5. Whether replay on reconnect includes missed executions. Crier does not promise stream replay or automatic REST backfill.

Use Webull's approved sandbox/test accounts where available. An unfunded production account is not a simulated account. Do not place a real trade solely to satisfy these checks; Crier itself never places orders.

## Inspect without posting

Keep both `CRIER_WEBULL_VERIFIED` and `CRIER_DELIVERY_ENABLED` false. Configure the Webull variables locally and start `python -m crier watch`. The private `audit` table in `data/crier.sqlite3` records observed payloads; the console shows capture-only or connection state. Request signing details and app secrets are not logged. SDK 3.0.3's verbose signing method is overridden to avoid its credential metadata prints.

`python -m crier export-history --output data/webull-history.json` performs a read-only query and saves **one page** of the response, including any pagination metadata. It refuses to overwrite an existing file. It does not normalize, post or replay those orders. Do not mistake one page for a complete baseline.

## Initial baseline

Before enabling validated monitoring, inspect all open orders and their existing cumulative fills. Capture a consistent snapshot while order activity is quiescent; canceling orders is not part of this tool. If a complete consistent snapshot cannot be obtained, remain in capture-only mode.

Prepare this local manifest, filling it with verified account data. For each already partially filled open order, include its cumulative quantity and average price. Omit zero-filled orders from `snapshots`; they have no prior execution balance. If there are no pre-existing partially filled orders, use an empty array. Fully completed historical orders can also be included to establish known watermarks. `complete_open_orders: true` is the operator's attestation, not an automated completeness check.

```json
{
  "account": "YOUR_ACCOUNT_ID",
  "environment": "sandbox",
  "captured_at": "2026-10-13T14:43:00Z",
  "complete_open_orders": true,
  "snapshots": [
    {
      "broker": "webull",
      "environment": "sandbox",
      "account": "YOUR_ACCOUNT_ID",
      "order_id": "BROKER_ORDER_ID",
      "symbol": "SPY261016C00600000",
      "category": "US_OPTION",
      "side": "BUY",
      "intent": "UNKNOWN",
      "cumulative_qty": "4",
      "average_price": "1.25",
      "occurred_at": "2026-10-13T14:42:18Z",
      "status": "PARTIAL"
    }
  ]
}
```

Use the actual capture timestamp and account/order data, not these illustrative values. Import with `python -m crier enroll --baseline data/baseline.json`. The import validates all rows and writes balances plus enrollment in one transaction. It refuses to overwrite an existing enrollment or order balance, including a delayed historical baseline arriving after a newer observation.

Only after validation set `CRIER_WEBULL_VERIFIED=true` and `CRIER_WEBULL_PRICE_MODE=cumulative_average`, then restart the observer. If a balance of four is enrolled and a later event reports five, Crier alerts only the new one. Events older than enrollment update baselines without posting. Without enrollment the observer remains capture-only even if verification flags are set.

Configure a dedicated informational Discord destination, then set `CRIER_DELIVERY_ENABLED=true` and restart the console process when ready. Startup does not prove successful Webull subscription; check Connections.

## Reconciliation and ambiguous delivery

Keep a backup of the SQLite database before operator maintenance. Pause delivery while investigating. Inspect private audit data and compare it with broker history. A source price correction blocks the order: later events cannot calculate a delta using the disputed basis. This release deliberately has no automatic unblock/replay action; reconciliation requires a reviewed repair or a future broker-specific reconciliation implementation.

For `uncertain` deliveries, search Discord for the public `Ref` on the message. A request may have succeeded even if no response arrived. Do not resubmit blindly. Preserve the original job and its evidence. There is no automated retry button for ambiguous sends. A future operator resolution UI can record confirmed message IDs and explicit resend decisions; the current release leaves these records held.

The SQLite audit file includes raw account evidence and is not encrypted by Crier. Protect it with disk encryption, OS permissions and private backups. Do not attach the raw database to GitHub issues. The UI does not expose raw observed payloads or credentials.

## Relevant official documentation

- [Event subscription and example payloads](https://developer.webull.com/apis/docs/reference/custom/subscribe-trade-events/)
- [Official SDK and environment hosts](https://developer.webull.com/apis/docs/sdk/)
- [Order query and delayed history caveat](https://developer.webull.com/apis/docs/reference/order-query/)
- [Connect API](https://developer.webull.com/apis/docs/connect-api/about-connect-api/) is the separate OAuth partner integration for platforms acting on behalf of customers. It is not required or implemented as a shared service in this self-hosted first release.

## Not yet validated

Real Webull connectivity, manual iOS order coverage, option-enrichment queries, reconnect replay, automatic history backfill, adjusted option multipliers, multi-leg strategies, position-level realized P/L, and actual iOS Safari behavior. These are explicit follow-on integration tasks, not hidden behind the passing synthetic tests.
