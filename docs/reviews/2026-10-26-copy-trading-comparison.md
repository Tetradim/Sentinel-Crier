# Copy-trading comparison and Crier code review

Date: October 26, 2026. Reviewed Crier `main` at `9626e4d`.

Scope: research comparable products, inspect Crier's execution/reporting paths and selected native lifecycle/UI code, reproduce actionable issues, and recommend controls. This is a review, not implementation approval or an activation of [deferred D.1](../deferred/multi-host-cross-broker.md). Competitor behavior below comes from primary vendor documentation; their proprietary implementations were not audited or benchmarked. Forex/MT-platform capabilities do not establish US equity-options support.

## Findings first

### R.1 [P1] Synchronous telemetry writes can stall the PC trading event loop

Location: [`CopyReporter.queue`, lines 21–22](../../crier/copy_reports.py#L21), called directly from the async reporter at [line 124](../../crier/copy_reports.py#L124). [`IntentDevice.db`, line 46](../../crier/intent_device.py#L46) allows a 15-second SQLite busy wait.

When another connection holds the device database's write lock, telemetry's `BEGIN IMMEDIATE` waits synchronously on the same asyncio thread that runs publication and receipt. Separate async tasks do not isolate blocking SQLite calls. This can consume the default 10-second entry window even though telemetry is intended to be independent of instruction delivery.

Reproduction: held a synthetic device database write transaction, scheduled a 50 ms event-loop heartbeat, and called the production telemetry queue. The heartbeat ran after **16.531 seconds**. No broker was contacted. This establishes behavior under database contention, not a claim that every trade experiences that delay.

Recommended fix: bounded nonblocking database admission or worker-thread isolation, preserving durable outbox retries and pairing/lifecycle fences. Add a regression asserting that publication/receipt and a heartbeat remain responsive while the telemetry database is locked. Do not solve it by dropping trading evidence or disabling reconciliation.

### R.2 [P2] Expired entries can be shown as received indefinitely

Location: [status selection, lines 65–76](../../crier/copy_reports.py#L65).

`collect()` considers broker order states and a narrow subset of executor results, but not the persisted skipped trade flag or the skipped decision/reason. With entries enabled, an expired instruction creates no broker order, so the report falls through to `received` with a null reason. Once the engine settles the event, that can remain its dashboard state.

Reproduction with the real local engine and a synthetic broker: expired entry → executor `skipped` → dashboard `received`, reason null, broker submissions **zero**.

Recommended fix: map durable execution decisions to the observational status/reason enums. Preserve `expired`, paused, quantity-cap and clock distinctions through safe human-readable messages. Use the existing audit trail when a settled event no longer appears in the current tick results. Cover restart as well as the initial rejection. This does not authorize retrying the expired order.

### R.3 [P2] One transient metadata failure leaves monetary reporting unavailable for the session

Locations: [Python attempt set, lines 102–111](../../crier/copy_reports.py#L102), [Android attempt set, lines 100–104](../../android/app/src/main/java/com/sentinel/crier/SyncService.kt#L100), and [iOS retained task, lines 1186–1191](../../ios/SentinelCrier/IntentMirroring.swift#L1186).

Python and Android mark a trade attempted before the lookup succeeds; iOS retains the completed task even when it returns no binding. Those guards prevent a later attempt during the same session. Host/legacy trades without a frozen verified binding can consequently keep currency/multiplier and P&L unavailable after the connection recovers. Reconnecting resets this attempt state; it is not permanent data loss across every restart.

Python reproduction: inject one transient metadata failure, make subsequent lookup calls eligible to succeed, and advance two reporting intervals. Result: **one call**, no cached binding. The equivalent native failure suppression is supported by static inspection, not a physical-device reproduction.

Recommended fix: distinguish in-flight, successful and retryable lookup states. Retry optional read-only metadata with bounded backoff and scope checks; keep it outside broker mutation and instruction receipt. Keep monetary values unknown until verified. This recovery should be automatic rather than another customer switch.

## Validation and limitations

- **130 focused existing tests passed** across intent execution, push, copy reports, dashboard arithmetic/privacy, execution policy and desktop policy UI.
- Three additional synthetic probes reproduced the behavior above. Their results are preserved in [reproduction evidence](2026-10-26-copy-trading-reproductions.json).
- No runtime source, application settings, Supabase deployment or broker connections were changed for this review. No broker orders or Discord messages were sent.
- This is a scoped review, not an exhaustive security audit or fresh physical/native acceptance. Existing phase-L acceptance is historical source evidence and does not invalidate these newly reproduced findings.

## Comparable products and lessons

| Reference | Documented useful behavior | Crier comparison | Recommendation |
| --- | --- | --- | --- |
| TradersPost | Strategy-to-account subscriptions, account-specific settings, disabled-on-creation subscriptions, signal and execution inspection. | Crier already pauses new receiver entries and provides durable audit/health; multiple simultaneous subscriptions remain deferred. | Borrow the clear subscription/account view and explicit activation, not a global broker selector. [Subscriptions](https://docs.traderspost.io/docs/core-concepts/subscriptions). |
| TradersPost concurrency/recovery | Account-and-symbol trade locking; execution-failure recovery is distinguished from retrying planning calls. | Crier already serializes its current engine and reconciles unknown submissions. Future independent host workers must share account coordination. | Preserve current serialization. Add account-wide coordination in D.1 before multi-host execution, without making the lock an optional safety bypass. [Trade locking release](https://docs.traderspost.io/releases/2026-10-02), [order behavior](https://docs.traderspost.io/docs/learn/platform-concepts/order-behavior). |
| Duplikium | Copy-link status modes, sizing methods, pending-order behavior and symbol/order filters. | Source/fixed/ratio/budget sizing, entry pause, exact/bounded/market pricing and optional entry timeout already exist in Crier. Symbol/asset entry filters and multiple active links do not. | Simplify existing controls first; consider entry-only filters. Keep link-level routing deferred. [Copy API settings](https://www.trade-copier.com/how-to/trade-copier-api-documentation). |
| FX Blue Personal Trade Copier | Sender/receiver configuration, filtering and an MT5 option to copy working requests before fill confirmation. | Crier already forwards saved instructions before host fills, with native clients rather than MT terminal installations. | Keep submission-first behavior and distinguish instructions from actual fills. Its forex/MT settings are design references, not portable US-options execution rules. [User guide](https://admiral.fxblue.com/appstore/u2/mt4-personal-trade-copier/user-guide). |
| SignalStack | A short signal-source → brokerage connection → order-routing setup, with multiple brokerage integrations. | Crier already has Host/Receive and separate Alerts journeys, but native execution currently centers on Alpaca; broker breadth is not parity. | Borrow concise connection/capability presentation. A vendor's broker listing does not prove every options order or account combination works. [Product documentation](https://signalstack.com/product/). |

Vendor latency/uptime claims were not independently measured and should not be used as Crier performance targets without equivalent end-to-end measurements. Crier's single hosted synthetic delivery sample is not a customer broker-execution benchmark. TradersPost also documents limits on execution retries and high-frequency use; do not mistake a retry setting for permission to resubmit an uncertain broker order. [Known limitations](https://docs.traderspost.io/docs/learn/known-limitations).

## What to retain

Crier's current strengths are durable instruction identity/cursors, rejection of expired entries, independent instruction and telemetry delivery, account/environment pinning, fresh reconciliation before another mutation, tracked-position exit limits, frozen policy snapshots, explicit receiver enablement and a read-only evidence dashboard. Keep those guarantees. Passing tests and clean arithmetic do not remove the need to fix the reporting/recovery gaps above.

Source/fixed/ratio/budget sizing and optional entry timeouts are implemented already; do not create a second parallel settings system. Continue using one validated policy model across Windows, Android and iOS. Keep new entries paused by default and exact-limit pricing as the conservative existing default; market orders remain an explicit user choice.

## Proposed controls and customizable inputs

These are recommendations, not controls added by this review. Defaults for new execution-changing filters require design and test work before activation.

| Control | Current support | Proposed presentation/default | Required semantics |
| --- | --- | --- | --- |
| Pause new entries | Implemented | Prominent control; receivers start paused. | Say that it prevents new entry submissions, continues host exits/cancels and does not itself cancel an already working broker order. Distinguish it from disconnecting all workers. |
| Copy sizing | Source/fixed/ratio/budget implemented | One selector; reveal only the relevant input. Preserve source-size compatibility defaults. | Show contracts/shares and a clearly labeled premium-based estimate; do not equate it to guaranteed broker buying power or loss. |
| Source and local quantity caps | Implemented | Separate labels and explanations. | A source-order filter and a local target cap are different. Never round an undersized order up past a configured cap just to satisfy a broker minimum. |
| Entry notional cap | Implemented in execution policy | Optional dollar input with fee exclusions visible. | It must remain enforced by the existing policy, not only a preview or UI widget. |
| Pricing and slippage | Implemented | Exact limit / bounded limit / market; show extra premium per share and equivalent per standard contract where verified. | Do not silently switch to market on timeout or rejection. Retain account and instrument price validation. |
| Entry freshness | Implemented; local max age is 1–30 seconds | Show effective age and source expiry together; existing default 10 seconds. | Increasing the local setting cannot extend an instruction past its original expiry. Keep freshness enforced. |
| Unfilled-entry timeout | Optional implemented policy | Off by default; label “Cancel my unfilled entry after …” and explain its acknowledgement-based timer. | Does not create an independent sell of filled holdings. Settings changes must not rewrite an old trade's frozen policy. |
| Stocks / options entry switches | Proposed | Explicit supported-instrument switches; preserve current compatible behavior until configured. | Apply to new entries only. Never filter the exit or cancellation of an already tracked trade. |
| Symbol allow/block lists | Proposed | Off unless configured; symbol picker and visible “only these symbols” summary. | Resolve option underlyings correctly; no wildcard that silently changes the actual contract. Preserve closes/cancels. |
| Entry schedule / timezone | Optional future control | Off by default; explicit timezone and preview of next allowed window. | Gate new entries only; no automatic flattening and no suppression of host exits because an entry window ended. |
| Failed/missed-trade notifications | Proposed improvement | In-app reasons always visible; optional OS/Discord notices, grouping and quiet hours. | Avoid repeated notification storms; do not hide unresolved-order status or send to Discord without configured authorization. |
| Friendly host/device/account names | Proposed near-term usability | Optional aliases, masked account identifiers and environment badges. | Aliases never replace authenticated identity, change destinations or expose private credentials/account IDs. |
| Dashboard price-detail sharing | Proposed privacy choice | Explain current sharing; optionally separate detailed fill-price sharing from status-only telemetry. | Do not suppress canonical instruction fields required for copying or falsely label an unverified fill. |
| Sizing/eligibility preview | Sizing preview exists | Keep it optional; label exactly which checks were performed and what is unknown. | A read-only preview is not trade permission and must not delay submission-first forwarding or become mandatory per-trade confirmation. |
| Push/poll transport | Automatic fallback implemented | Show current transport and last success; automatic mode. | Keep recovery automatic. Do not offer a “fast mode” that bypasses auth, durable storage, expiry or ownership checks. |

## What to hide, consolidate or leave out

- Move raw pairing JSON, internal UUIDs and protocol payloads into Advanced/Support views. Show friendly names and a short relevant reason in the normal flow; retain exportable technical evidence.
- Consolidate basic/advanced sizing and pricing controls around the existing validated model. Show only inputs relevant to the selected mode; do not delete recovery journals or diagnostic APIs to reduce visual clutter.
- Clearly badge brokers as execution-capable, read-only, experimental or awaiting approval. Do not show an unimplemented adapter as ready to trade.
- Do not add reverse copying, independent take-profit/stop-loss/trailing exits, automatic contract substitution or host-opposing strategies under this request.
- Do not add blind broker POST retries, automatic market fallback, automatic enabling after restart, or automatic copying of old/open host positions. Those would change the approved execution semantics or risk duplicate/stale submissions.
- Keep uncertain-order reconciliation, account/environment fences, idempotency and ownership limits mandatory. They should not become customer-disableable switches.
- Do not add every competitor control. A shorter effective-settings summary is more useful than dozens of unfamiliar switches.

## Recommended follow-up order

1. Fix R.1–R.3 with focused regressions before adding more execution modes. Make telemetry failure visible without putting it on the trading critical path.
2. Improve current single-connection UX: effective-settings summary, friendly aliases, exact skipped/blocked explanations and supported-capability badges.
3. Design and test optional entry-only instrument/symbol filters and notification preferences. Keep existing defaults and host exits intact.
4. Keep multi-host, multi-account and cross-broker execution in **deferred D.1**. Its shared account reservations, per-host allocation and loop protection must precede fan-out execution. Do not implement it as several independent copies of today's engine spending the same account funds.

No runtime fixes or new trading controls were activated by this review. The recommended first work is correcting the reproduced defects, not expanding the feature list.
