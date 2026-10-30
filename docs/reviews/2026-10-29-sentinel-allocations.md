# Sentinel allocation and multi-account source review

Reviewed October 29, 2026, from local source under `C:/Users/automation/GitBots`. Targeted source inspection across the Sentinel line, not a complete audit of every file or a claim of live broker acceptance. Donor bots were not modified, started or tested. No secrets/logs were inspected; no broker orders or Discord messages were sent.

## Pulse is the primary allocation model

Pulse's reusable per-ticker/per-destination allocation fits the owner's model: a $1,000 SPY card can buy/sell repeatedly as confirmed exits free its allocated capacity. For Crier, replace the ticker card with a host/account/asset allocation, while preserving the host as the entry/exit authority.

Sources:

- `Sentinel-Pulse/frontend/src/components/settings/BrokerAllocationsSection.tsx:105-129`: per-destination allocation editor, summed `base_power`, persistence and rollback on failure. Reuse the editable allocation-card pattern, not its provider-keyed identity.
- `Sentinel-Pulse/backend/broker_manager.py:262-340`: explicit assigned-destination fanout and independent results; unavailable destinations are skipped without borrowing another account. A common template quantity can override allocation-derived quantity, so Crier must freeze a separate sized plan for each destination rather than copying a global quantity.
- `Sentinel-Pulse/backend/trading/live_cycle_capital_patch.py:62-158,230-284`: account capacity, outstanding buy reserves, other strategy allocations, fee-adjusted cycle capital and optional compounding. Its read failures return zero reserve/other allocation and scans are capped; do not import those fallbacks as authority to spend shared customer funds. A verified shared ledger must block new admissions on incomplete evidence.
- `Sentinel-Pulse/backend/trading/live_broker_scope_patch.py:6-16`: zero future allocation does not remove the broker from sell reconciliation. Preserve this behavior for host-directed exits and existing holdings.
- `Sentinel-Pulse/backend/broker_manager.py:77,107-110,165-179`: adapters/credentials are keyed by broker name and generated duplicate keys use symbol/side/quantity/type/second. Crier needs actual broker/account/environment plus host/route/event/revision identity; two accounts at the same provider must remain distinct.
- `Sentinel-Pulse/backend/trading/live_broker_capability_patch.py`: several named adapters are explicitly unavailable until cumulative fills/cancellation/restart recovery are verified. Adapter presence is not execution readiness.

These are differences to harden for Crier's multi-host/options use. They do not change Pulse's stock-only recurring allocation objective or authorize changes to Pulse.

## Other donor findings

| Project | Useful code inspected | Crier adaptation and limits |
| --- | --- | --- |
| Echo | `backend/risk.py:175-239`; `backend/unified_risk.py:86-133`; `backend/bot_managed_exits.py` reconciliation | Use verified option cost and whole-contract floor. The stronger risk helper can return zero; the older unified helper forces at least one, which must not defeat a strict Crier allocation. Trailing/independent exits remain separate work. |
| Iron | `src/sentinel_iron/portfolio/position_sizing.py:40-107`; `domain/portfolio.py` | Decimal arithmetic, account-equity snapshots and account-wide cap patterns. Its volatility risk fraction is not the same as purchase-premium allocation; do not substitute futures volatility sizing for option cost. |
| Chain | `src/sentinel_chain/risk.py:9-30,79-116` | Separate per-order, aggregate and account-equity caps. Crypto leverage/short signals/stops are not Crier copy authority. |
| Edge | `backend/shared/handoff.py:57-124`; `backend/pulse_client.py` | Typed intent identity, validation and circuit-aware transport. Keep host commands separate from local allocation decisions; do not import autonomous strategy actions. |
| Link | `apps/external-helper/src/store.js:227-299` | Durable ownership/lease/claim fencing patterns. A delivery lease alone is not a shared brokerage cash transaction. |
| Nexus | `packages/contracts/src/reconciliation.ts:45-70`; `events.ts:9-20,39-93` | Requested vs executed outcomes, lease/proof identity and reconciliation. In-memory events alone do not establish durable funding reservations. |
| Core | `server/relayPolicy.ts:4-65` | Explicit observational-message authority boundaries and scoped relay admission. Its account display fields are not order permissions or an execution ledger. |
| Flare | `darkpool/trade_intent.py:22-69` | Explainable risk/decision previews. Its estimated-share and stop-risk plan is not a multiple-account executor. |
| Archive | `sentinel_archive/bot_suite/planner.py:12-39,67-69` | Deterministic fingerprints and broker-free replay planning; suite planner rejects live execution. Compute budgets are not brokerage allocations. |
| Crier | `crier/execution_policy.py`, `policy_preview.py`, `policy_journal.py`, `desktop_connections.py` | Existing fixed/ratio/dollar sizing, frozen trade policies and isolated connections remain. New reusable pool/percentage reference does not yet authorize orders or replace the same-account guard. |

## Reviewed local revisions

| Repository | Commit |
| --- | --- |
| Pulse | ff89b28ce7cefbb5c7f07017d30658dccd6df51f |
| Echo | c0e463e150c2ef69843f8ae84caf8844c58a4671 |
| Edge | 381451e7daa2903101b8485b195079b95c8b756b |
| Core | ba1df45b6e33b23e8776072a6549dda230e61785 |
| Chain | 8b6ec426a249b72c14446957793fdf180fbb8c2c |
| Iron | 3753d09fa5f7ac3ee1872fd4a1b7a98a27ebc491 |
| Flare | c04a466001be64eec5027a5f596053c74a6184d6 |
| Link | 5e9f1aa53faea2ef6cb12191e67c3e5b1e6359d7 |
| Nexus | 4aefef90a79c963a0d9290b629980b01f1be75d5 |
| Archive | 614abdcad1973707cbc7664bcd42ececbcd1f695 |
| Crier base | 3d86514 |

## Crier allocation model

Two independent settings per host/account/asset pool:

1. **Reusable host allocation:** maximum combined held, pending and uncertain exposure in whole units, dollars or percent of that destination account's equity.
2. **Entry size:** fixed whole units, dollars or percent of the destination account's equity per new admitted trade. Separate quantity/notional guards still apply.

Percent is purchase/exposure allocation, not a stop-loss risk percentage. An illustrative 2% of $10,000 produces a $200 entry budget; for a verified standard 100-multiplier option at a final $0.20 limit, that is 10 contracts before explicit fee reserves. The host's requested exit acts only on that host's owned fills. A lowered/zero allocation blocks future entries without forcing a sale. Fixed-dollar pools remain fixed unless an explicit future compounding policy is selected.

Each account gets one coordinator, with many host subscriptions referencing it. It must atomically reserve capacity, freeze entry plans, preserve unknown orders across restart, attribute fills/fees/lots to the correct host and release capacity only from authoritative terminal/fill evidence. Broker-reported available cash may already include working-order holds: reconcile snapshot coverage instead of subtracting the same reservation twice. Cash, unsettled proceeds and leveraged buying power are not interchangeable. No funds move between accounts or broker providers.

The existing same-account route exclusion remains until this coordinator is wired into every execution path. Simply removing that check would not implement shared-account copying. Contract mapping, provider grants and actual Webull/Tradier execution remain separate dependencies.

## Implementation progress

`crier/host_allocation.py` provides a **preview-only** reference: scope and host/asset isolation, explicit USD funds, account-snapshot freshness, unit/dollar/equity-percentage pools, independent entry sizing, fee reserve, whole-unit rounding and explicit optional downsizing. It has no network, persistence, broker imports or order authority. `tests/fixtures/host-allocation.json` contains five portable parity examples for future native implementations.

29 new tests passed; 129 tests passed across allocation preview and related existing sizing/execution-policy suites. Shared durable ledger, live admission, route migration and native allocation controls remain unfinished. See [implementation plan](../superpowers/plans/2026-10-29-host-allocations.md).
