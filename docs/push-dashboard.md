# Push delivery and copy dashboard

Crier sends the saved order instruction immediately. It does not wait for the host's fill before forwarding the instruction. Broker reconciliation then sends separate observational updates. Receiver sizing, entry expiry, pause, lifecycle fences and uncertain-order reconciliation still apply.

Open **Copy dashboard** on Windows, Android or iOS to see the host's instructions and each permitted device's reported quantities, target, fills, remaining tracked units and connection status. The host sees its receivers; a receiver sees the host and itself. Joining a channel shares this tracked trade evidence with its host. Broker credentials, account balances and unrelated holdings are excluded.

The dashboard is read-only. It cannot place trades, retry an order, change the host's strategy, set an independent stop or sell a receiver early.

## Delivery

The authenticated `/api/sync/stream` connection carries durable instruction pages and dashboard snapshots. Supabase private database notifications wake the Edge Function after committed writes. Local connection servers use committed in-process notifications and must continue using one worker. Notifications contain a channel hint; the service rereads and reauthenticates durable records before delivering anything.

Streams rotate within 90 seconds and recover from the saved cursor. On an unavailable stream, devices use bounded polling and show **poll**, rather than claiming push. A reconnect can replay events; existing durable identities suppress duplicate submissions. A network outage, broker preflight, the broker itself, or OS suspension can increase delay. A local socket regression test is not a claim about real cross-state latency.

Instructions and observational reporting use separate workers. Missing dashboard data does not block order receipt or imply a position is closed. Device-reported broker evidence is labeled with observation and server receipt times; it is not independently attested by the relay.

## Prices and money

Entry and exit averages come from cumulative broker fill quantity and average-price evidence. Receiver minus host comparisons use actual averages; near-event quote comparisons remain separate. Clock-adjusted delivery estimates require matching recent clock samples and show their uncertainty.

Closed-trade gross P&L requires equal positive bought/sold quantities, complete prices and verified currency/contract size. Net P&L requires complete actual fees. Unknown fees are not assumed zero. Partial realized P&L is unavailable because Crier does not invent lot allocation. Open estimates require verified cost metadata and an observed bid no more than five seconds old; they are estimates, not executable proceeds. Existing near-event quote captures may supply that evidence briefly; this feature does not add a continuous quote subscription.

Snapshots are bounded: 50 latest tracked trades and up to 200 members, statuses and diagnostics. A truncated snapshot is labeled and has no complete portfolio total. Missing, stale or oversized evidence remains unavailable.

## Deployment and acceptance

The testing Supabase project has migration `20261026104201_push_dashboard.sql` and the updated Crier Edge Function deployed. An isolated synthetic channel verified streamed delivery, matching durable cursors, reported-price arithmetic and receiver revocation without broker orders or Discord posts. Initial subscription probes returned 503 before a later probe succeeded; recovery remains explicit rather than promising an always-available stream. Keep the service-role key exclusively in the service runtime. Native clients continue using their scoped pairing tokens.

See the [implementation plan](superpowers/plans/2026-10-26-push-dashboard.md) for current verification and deployment status. Physical-device, real broker-UI and cross-network acceptance remain separate from automated source tests.
