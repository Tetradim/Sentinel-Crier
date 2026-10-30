# Host allocations and shared destination accounts

**Goal:** Give each host/account route reusable exposure allocation in units, dollars or percentage of destination equity, independently from per-entry sizing. Preserve host-directed exits and per-host holdings.

**Architecture:** Separate account connections from host subscriptions. One account coordinator owns verified broker identity, account reads, order dispatch and a transactional reservation/lot ledger; several host subscriptions reference it. Never lift the existing same-account route guard merely because sizing arithmetic exists. Amounts use Decimal/canonical strings, verified standard contract multipliers and frozen admission snapshots. Percentage means destination account equity, not host account value, buying power or stop-loss risk. Shared ledger must derive spendable cash without double-counting broker-held order reservations. Zero allocation pauses entries but cannot remove exit/reconciliation authority.

## Tasks

- [x] Inspect all local Sentinel repos and record reusable patterns/limitations, particularly Pulse reusable per-destination allocations.
- [x] Add/test non-executing allocation arithmetic for unit/dollar/equity-percent host pools and independent entry sizing; exact scope/freshness checks and shared portable cases. Files: crier/host_allocation.py, tests/test_host_allocation.py.
- [ ] Build durable account-level reservations and per-host lots, including unknown submissions, partial fills, confirmed exits, concurrent hosts, manual broker discrepancies and restart recovery. Account key includes broker/account/environment; submission ID includes host/route/event/revision/destination.
- [ ] Integrate Windows account coordinator and allocation editor. Existing single-route legacy execution remains valid; no silent migration/rebinding or auto enablement. Only then replace same-account exclusion with verified shared-account admission.
- [ ] Port ledger/preview rules and route UI to iOS and Android using identical fixtures; preserve global drain and device credential custody.
- [ ] Validate funded fanout across distinct accounts and several hosts sharing one account, contradictory evidence, quota/freshness limits and support exports; run native/packaged CI.

Defaults: budgets reusable after confirmed exits; fixed dollars do not compound automatically. Percentage pools refresh for new admissions using fresh destination equity. Existing exposure above a lowered cap blocks new entries without forced sales. Money-limited sizing requires a finite final buy limit; market estimates cannot guarantee a monetary cap. Round down whole supported units; never force a minimum contract that exceeds a cap. Independent strategies, trailing/fallback and additional broker execution adapters are separate work.

Source review: [Sentinel allocation findings](../../reviews/2026-10-29-sentinel-allocations.md). Initial reference verification: 29 new tests; 129 allocation and existing policy tests passed. Reference math is not execution integration.
