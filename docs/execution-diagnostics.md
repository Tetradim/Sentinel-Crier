# Execution diagnostics

Execution diagnostics run separately from order delivery on Windows/Python,
iOS, and Android. Each client retains local execution evidence and captures a
near-event Alpaca quote. Receivers also fetch the host's observation for the same
event to compare premiums and estimate instruction-delivery time.

## Open a report

- **Windows:** Connect to the saved account, select a trade in **Trading & activity**,
  open **Diagnostics**, and select **Load selected trade**. Reload as new evidence
  arrives. Select buy or sell for the comparison side; export JSON or CSV.
- **iOS:** Open the tracked trade's diagnostics from the intent trading screen.
  Each revision has its own timeline, premium comparison, delivery estimate,
  and JSON/CSV sharing controls.
- **Android:** Open **Diagnostics** to inspect recent tracked events, then share
  or save JSON/CSV using Android's native controls.

Reports preserve event identity and revision. Local evidence includes submission,
relay delivery, cancellation, broker status, cumulative filled quantity and average
fill price when available. Diagnostic writes are best-effort: this is troubleshooting
evidence, not a guaranteed audit ledger. Receiving an instruction is not a broker fill.

Exports include execution evidence and quote/timing observations. Neither export
includes broker credentials or pairing tokens. Files contain trade information;
choose their destination accordingly.

## Premium capture

Capture uses each device's Alpaca credentials and a separate request to the
market-data service. Stocks request **IEX**, a limited market view; options request
**OPRA** explicitly. OPRA access depends on the account's market-data entitlement.
There is no automatic fallback to indicative or delayed options data.

Only matching event revisions and feeds are compared: ask-to-ask for a buy and
bid-to-bid for a sell. Snapshots must be within five seconds of the event and
fresh at capture. These are asynchronous near-event snapshots, not the exact
premium when the button was pressed, guaranteed executable prices, or fills.
Unavailable, stale, or invalid evidence is labeled instead of replaced by the
order limit. Quote requests and diagnostic retries never wait in the broker
submission path.

## Delivery timing

Both devices probe the shared relay clock and retain their local offset and
round-trip uncertainty. The receiver compares corrected sender and receiver
observation times for the same event. The display shows an **estimate with an
uncertainty range**, not a guaranteed latency. This measures instruction delivery,
not brokerage acceptance or time to fill.

Missing or stale clock samples, clock jumps, and inconsistent evidence make the
estimate unavailable. A first trade before the initial clock probe can therefore
have no timing estimate. Keep the relay clock synchronized; a relay clock change
between the two probes can invalidate the estimate.

## Deployment and privacy

Deploy the updated connection service and rebuild both clients to use the new
`/api/sync/clock` and `/api/sync/diagnostics` endpoints. Existing intent transport
still works with older clients, but they cannot supply the new observations.
No hosted service is provisioned by these code changes.

The relay sees the diagnostic observations. Each receiver can retrieve the host's
observation and its own, never another receiver's. Hosts can see their local
evidence; receiver comparisons are displayed on receivers. This does not collect
all remote broker execution timelines into a centralized dashboard.

Clients retain local evidence and retry diagnostic exchanges a bounded number
of times. Network outages or exhausted capture capacity may leave incomplete
reports without stopping orders. iOS foreground requirements and Android service
limitations still apply. Test paper-account delivery on actual devices before
relying on operational measurements.

See the [diagnostics protocol](protocol/diagnostics-v1.md) and
[paper acceptance checklist](intent-paper-acceptance.md).
