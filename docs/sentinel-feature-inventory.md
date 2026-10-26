# Sentinel reuse inventory and proposed Crier controls

Reviewed October 26, 2026. Local source root: `C:/Users/automation/GitBots`. Only Crier was modified. No other bot was started, no credentials were inspected, and no broker orders or Discord messages were sent.

The owner authorized using Sentinel code to repair the three reviewed Crier defects and requested a list of possible independent trading features. The repairs are implemented separately from this inventory. **Independent entries/exits, stops, trailing and automatic market fallback are proposals here, not activated features.** Multi-host/cross-broker execution remains [deferred D.1](deferred/multi-host-cross-broker.md).

## Source revisions inspected

| Repository | Reviewed local commit |
| --- | --- |
| Echo | `c0e463e150c2ef69843f8ae84caf8844c58a4671` |
| Pulse | `ff89b28ce7cefbb5c7f07017d30658dccd6df51f` |
| Edge | `381451e7daa2903101b8485b195079b95c8b756b` |
| Link | `5e9f1aa53faea2ef6cb12191e67c3e5b1e6359d7` |
| Core | `ba1df45b6e33b23e8776072a6549dda230e61785` |
| Chain | `8b6ec426a249b72c14446957793fdf180fbb8c2c` |
| Iron | `3753d09fa5f7ac3ee1872fd4a1b7a98a27ebc491` |
| Flare | `c04a466001be64eec5027a5f596053c74a6184d6` |
| Nexus | `4aefef90a79c963a0d9290b629980b01f1be75d5` |
| Archive | `614abdcad1973707cbc7664bcd42ececbcd1f695` |

Source paths below are relative to the named repository. These are source-inspection results, not certification that every adapter has completed live acceptance. Referenced donor tests were inspected, not executed in this task.

## Applied to the three Crier defects

| Defect | Useful Sentinel pattern | Crier adaptation |
| --- | --- | --- |
| R.1: telemetry SQLite waits block the PC event loop | Echo `backend/database/abstraction.py:679–801` awaits database I/O; Link `apps/external-helper/src/store.js:18–23,339–356` serializes asynchronous persistence and bounds retryable writes. | Keep Crier's schema and standard-library dependencies. Offload telemetry collection, settings reads, queue/ack writes and pending reads through a cancellation-drained worker boundary; give telemetry writes a short busy timeout and retain retryable work. Do not import Echo's older synchronous SQLite layer. |
| R.2: skipped entries remain labeled received | Echo `backend/fill_reconciliation.py:69–131` preserves failed/pending/unconfirmed outcomes and reasons; Nexus `packages/contracts/src/reconciliation.ts:41,77,113` distinguishes requested, executed and simulated states. | Add Crier-specific durable decision evidence, atomically save skipped flag and reason, and map it to existing report enums after settlement/restart. Keep broker submission and fill truth unchanged. |
| R.3: first failed metadata lookup suppresses recovery | Echo `backend/fill_monitor.py:142–163` keeps optional read/status work asynchronous and retries transient status failures; its tests include `test_transient_status_error_keeps_polling_until_fill`. No ready-made metadata retry state machine was found. | Separate in-flight, successful and retryable states on Python, Android and iOS. Use monotonic capped backoff of 5,10,20,40,80,160,300 seconds, then 300; current 15-second worker/report ticks can make attempts later. Fence late results by session/pair/account and keep reads outside order submission. |

This reuses architectural patterns, not whole database/broker modules with incompatible schemas. Crier's durable identities, account/environment pinning, unknown-submission handling and lifecycle fences remain in force. Repair source: `a7b332b`; verification is recorded separately from the donor-source review.

## Echo trailing stops: preferred source to adapt

The stronger implementation is `backend/options_exit_policy.py:129` (`evaluate_coordinated_exit`), reached from `backend/bot_managed_exits.py:281–294`. It is more suitable than the simpler `backend/trailing_stop_engine.py:8` helper.

Its actual policy does the following:

1. Requires remaining owned quantity, entry price and an executable option bid. It rejects stale or undated quote observations before evaluating stops (`options_exit_policy.py:138–148`).
2. Advances a persisted high-water mark from the executable bid (`:150–158`); a non-executable mark high is not equivalent evidence.
3. Arms trailing only after configured percentage and minimum absolute premium activation thresholds (`:468–484`).
4. Calculates distance using the widest of the configured percentage distance, minimum cents distance and spread-derived distance (`:500–508`). Progressive tightening and elastic modes are evaluated separately (`:551`).
5. Once armed, ratchets the floor with the previously persisted floor so it cannot move downward when the spread or an elastic distance widens (`:509–515`).
6. Produces an exit decision when the bid crosses that floor, subject to allocation/runner rules (`:517–539`). A trigger is not a confirmed broker fill.

The worker reconciles pending exits before evaluating another exit (`bot_managed_exits.py:38–54`). It reserves an exit quantity before broker submission (`:942–957`), records a distinct child order, and applies confirmed fills through reconciliation. Cancellation/repricing checks occur before replacing an unresolved exit (`:1327–1396`). These lifecycle dependencies are as important as the trailing formula.

Tests worth adapting include `backend/tests/test_options_exit_policy.py:90,605,699,848,883,1099`: executable-price selection, floor ratcheting, distinct confirming quotes and stale-quote rejection. Exit worker/fill tests cover reservation before submission, partial fills, duplicate suppression and cancellation races.

### Do not transplant these assumptions unchanged

- The simpler trailing helper does not itself check quote freshness or preserve a separately ratcheted floor. Its `trailing_stop_cents` is directly subtracted from premium (`trailing_stop_engine.py:56–66`); another policy converts cents by dividing by 100. Normalize input units explicitly.
- Echo policy arithmetic uses floating point in places. Adapt monetary boundaries to Crier's decimal evidence and destination tick rules rather than copying calculations indiscriminately.
- A local bot-managed trail depends on the supervising app/worker remaining available. A broker-native protective order has different capabilities and failure modes. iPhone suspension limits do not disappear when a trailing function is added.
- An armed stop is a price trigger, not a guaranteed execution price or maximum loss.

## Proposed independent entries and exits — D.2

Status: **Requested feature inventory; design candidates, not activated.** Keep future authority choices explicit:

| Proposed mode | Meaning | Proposed default |
| --- | --- | --- |
| Host follow | Follow host entry/change/cancel/exit instructions, with existing local sizing and authorization controls. | Preserve current default. |
| Host follow + receiver protection | Receiver may close its own tracked allocation earlier under explicitly enabled protective rules. Later host exits must recognize already closed units. | Off until deliberately configured. |
| Independent strategy | A separate local strategy originates its own entries/exits with its own ownership and funding records. Never attribute those trades to the followed host. | Off; requires separate live integration/acceptance. |

Do not run an Echo exit worker alongside Crier's existing executor against the same holdings. Integrate decisions through one serialized mutation/reservation boundary. Freeze each trade's authority and policy at admission; changing a toggle must not silently rewrite open trades.

### Feature candidates and inputs

| Feature | Actual source evidence | Candidate inputs / integration requirements |
| --- | --- | --- |
| Fixed protective stop | Echo `bot_managed_exits.evaluate_position_exit:281`; coordinated hard-stop helper `options_exit_policy.py:749`. | Enable, percent or explicit price, quote age, confirmation count/dwell, quantity to protect, authority scope. Distinguish a local trigger from a broker-native order. |
| Trailing stop | Echo coordinated policy above. | Enable, activation percent, minimum activation cents, trailing percent, minimum distance, spread multiplier, tightening/elastic mode, quote age, runner allocation. Persist peak and floor through restart. |
| Break-even / profit floor | Echo coordinated exit and core/runner policies. | Enable, arming threshold, floor/offset, reserved runner quantity; arm from actual fills and owned units. |
| Staged take profit / partial exits | Echo `options_exit_policy.py`, `core_runner_policy.py:51,152`. | Stage thresholds and contract/share amounts or percentages. Complete a stage on fills, not merely a submitted order. Core/runner allocation is not stock/options funding allocation. |
| Independent signal entries | Echo `strategies_library.py:66,117,169,227,285,339` contains mean-reversion, momentum, breakout, RSI, MACD and Bollinger classes. | These were found in strategy/backtest/optimization code, not verified as a complete live autonomous entry path. Need strategy-specific activation, data freshness, instrument selection, allocation and no-feedback-loop ownership before live use. |
| Scale-in / reentry rules | Echo `entry_controls.py:85`; entry alignment `entry_alignment.py:37,65`. | Explicit allow/deny, per-trade cap, existing-contract handling and price alignment. Do not reopen a completed protective exit just because an old host instruction is replayed. |
| Time / 0DTE exit | Echo `bot_managed_exits.py:375,557`. | Enable, explicit market timezone and cutoff, affected expiry/owned quantity, pending-order treatment. No assumption every broker accepts the same session/order type. |
| Risk-priority exit scheduling | Edge `backend/retry_queue.py:30–115`; Echo pending-exit priority/repricing. | Coalesce competing host/protective exits over the same owned quantity, with one reservation and reconciliation authority. Edge's in-memory queue is not a replacement for Crier's durable outbox. |
| Automatic market fallback | Not found as a completed Echo feature. Echo's verified exit path submits priced limit orders (`bot_managed_exits.py:959–968`; Alpaca/Tradier adapter limit payloads). Repricing and cancellation are not market fallback. | Separate entry/exit enables, eligibility reason, timeout, maximum attempts and supported broker/order classes. See lifecycle below. Default off. |

### Automatic fallback needs a new lifecycle

For either an entry or exit: retain the first order's identity, request cancellation, reconcile cancellation and any late/partial fill, calculate only the still-owned/unfilled remainder, then reserve and persist a new child order before submission. An unknown first POST/cancel must not authorize a second order.

Keep entry instruction expiry and account/funding caps. An entry rejected for insufficient funds, missing permissions or wrong contract is not a reason to retry as market. Market execution cannot enforce a strict price cap; if a hard cap is required, evaluate a bounded aggressive limit instead. Do not silently migrate the trade to a different broker. Pulse's explicit market-or-limit stop template (`trading/broker_execution.py:111–130`) is a request-builder reference, not a finished fallback lifecycle.

## Multiple brokers: reusable structure and limits

| Bot | Useful code | What it does not establish |
| --- | --- | --- |
| Pulse | `backend/brokers/registry.py:10,140,155`, async port `brokers/base.py:111,121`, and `broker_manager.py:262,321` provide adapter discovery and isolated fan-out results. | Pulse is stock-only; its equity-shaped order model/Tradier path is appropriate to that scope. Crier options reuse would require contract identity/open-close/multiplier/funding fields. Registry labels alone do not establish acceptance. |
| Echo | `backend/broker_clients/__init__.py` contains Alpaca and Tradier option-aware paths and fill reconciliation. | The Webull class at `:1004` explicitly reports not implemented; a broker name/factory row is not an executable Webull integration. Other adapters need their own current capability review. |
| Iron | `src/sentinel_iron/brokers/routes.py:19,26` has a route bundle/factory; catalog separates executable from documentation-only routes. | Its inspected adapters are futures-oriented, including IBKR `FUT` and tastytrade `Future`; do not treat them as US stock/option adapters. |
| Chain | `src/sentinel_chain/live_execution.py:79,121` explicitly blocks unsupported live policies; CCXT port is reusable crypto infrastructure. | Inspected live mapping targets Bitunix futures. Paper bracket/trailing features are not live US-options capability. |

Preserve Pulse's useful rule that accounts with zero **future entry allocation** still participate in sell reconciliation (`backend/trading/live_broker_scope_patch.py:6–18`). Removing an allocation must not strand an existing position's exit.

Do **not** import Pulse's manager idempotency unchanged: `broker_manager.py:107–110` uses symbol/side/quantity/type/current-second without broker/account, so identical parallel destination orders can collide. The inspected production path also does not establish a write-ahead, restart-safe identity journal. Keep Crier's durable scoped identities and extend them deliberately for D.1.

## Separate stocks/options and allocation of funds

Crier already represents both stocks and options in its canonical protocol; this work is about independent enablement, funding and policies, not simply renaming an options-only field.

No complete, atomically conserved stock-versus-option allocation ledger was found in the inspected Sentinel code. Echo `backend/risk.py:175–244` is option-contract sizing (`entry premium × 100`), not a generic stock/options allocator. Its estimated-loss calculation includes a minimum-one-contract floor; do not import that as a strict budget guarantee. Pulse's capital helpers subtract working buys and other allocations; observation-query failures can return zero. That warrants tracing error handling, card budgets and concurrent execution before concluding that Pulse can overspend. A capacity helper alone does not establish or disprove system-wide reservation guarantees.

Owner clarification: Pulse intentionally reuses assigned stock-card capital over repeated price/percentage-triggered buy/sell cycles. Unlimited cycles do not mean unlimited simultaneous funds. Its stock-only model and lack of options pools are not defects. Crier's proposed shared stock/options ledger is an additional requirement, not a correction to Pulse's purpose. See [future scope](future-scope.md) for an optional recurring-card adaptation and the separate identity/recovery concerns.

Proposed controls:

- Independent **Allow new stock entries** and **Allow new option entries** switches. Turning either off must leave existing owned positions eligible for reconciliation and authorized exits.
- Per-account stock and option entry budgets, defined as dollars or explicit percentages of a clearly defined new-entry funding pool, with a separately stated unallocated cash reserve. Budgets must fit within verified account capacity after committed costs/reservations.
- Separate per-trade caps, maximum concurrent allocations and sizing policies for each asset type. Shares use stock pricing/lot rules; options use verified contract size, premium, expiry and open/close intent. Do not assume every option deliverable is 100 shares.
- Reserve cash/quantity atomically before any order across all hosts and both asset pools. Include outstanding buys and unknown submissions. Release only from broker-confirmed unfilled/canceled quantities; do not recycle money just because a cancel request was sent.
- Explicit policy on unused allocation: strict separation first; any optional borrowing between stock and option pools requires a defined cap and audit trail. No automatic brokerage cash transfer or automatic sharing of one account's buying power with another.

Illustration only: from a $1,000 new-entry budget, $400 stocks + $400 options + $200 cash reserve. A $100 pending stock buy consumes the stock pool and the shared account reservation; it cannot leave the same $100 available to another host's option order. This is an accounting example, not a recommended portfolio allocation.

## Other Sentinel features worth preserving or adapting

| Bot | Useful implementation | Crier use / caution |
| --- | --- | --- |
| Link | `apps/external-helper/src/store.js` serialized snapshots, durable leases, stale claimant checks, expiry and bounded Windows file-write retries. | Reliable delivery/evidence persistence patterns. Discord job retry is not permission to repeat a broker POST, and independent in-memory stores are not a transactional shared funding ledger. |
| Edge | `backend/shared/handoff.py:10–124` typed actions and scoped identities; `pulse_client.py:42–105` circuit-aware handoff. | Versioned decision transport and stale-aware dispatch; retain Crier durable replay and adapt order authority explicitly. |
| Core | `server/relayPolicy.ts:4–65` restricts observational destinations, endpoints and event types. | Keep observed signals/health separate from execution commands. Its synchronous event append is not an async database fix. |
| Nexus | `packages/contracts/src/events.ts:109–130`, reconciliation and lease proof contracts. | Preserve requested/submitted/executed/simulated distinctions, source/broker IDs and stale/conflicting-proof rejection. Its inspected event log is in-memory, not crash durability. |
| Flare | `darkpool/trade_intent.py` explanatory gates, source confirmation and risk-plan representation. | Potential decision-preview UX. Its verified gateway requires manual execution; do not advertise an autonomous broker adapter. |
| Archive | `sentinel_archive/recording_store.py:12,28,153,171,660` async source/quote/bar capture. | Broker-free replay fixtures and provenance. Loading old recordings must not automatically create live copy orders. |

## Proposed work order

1. Complete verification of the R.1–R.3 repairs, retaining the current trading authority and defaults.
2. Design D.2 authority, quote/floor persistence, owned exit reservation and the common host/protective-exit coordinator before importing any stop/trailing worker.
3. Adapt Echo's pure coordinated policy and its freshness/ratchet/fill tests, using Crier-specific decimal/tick/account bindings.
4. Add separate stock/options controls and a shared reservation ledger; trace Pulse's complete card-budget/concurrency/error path before adapting its capital helpers. Its stock-only recurring allocation model is valid for its own purpose.
5. Add optional fallback only after cancel/late-fill/unknown-submission tests prove one remaining quantity and one destination order authority.
6. Resume D.1 multi-host/multi-account/cross-broker routing only when deliberately selected later. Provider approvals, Apple signing and real/physical acceptance remain separate dependencies.

This is a source-backed feature list. It is not a promise of guaranteed fills/profit, a claim that every named broker works, or activation of autonomous policies.
