# Runtime follower policy contract

Implements the approved H.5 design. User authorization covers source work and tests, not real account orders. Keep existing default behavior and old open trades. Work directly on main; root integrates commits. Never change source wire events or silently reinterpret an old journal as an advanced policy.

## Local configuration

Add nullable `execution_policy` to local settings/config/preferences. Absent/null means legacy. A selected object has defaults:

```json
{"version":1,"mode":"source","fixed_quantity":null,"ratio_bps":null,"budget":null,"max_source_quantity":1000,"max_local_quantity":1000,"max_entry_notional":null,"exit_mode":"requested","entry_timeout_seconds":null}
```

Modes are source/fixed/ratio/budget; exit modes requested/proportional/close_tracked. Sizing validation matches `crier/policy_preview.py`: strict integers (never bool), whole units 1–1000, ratio 1–10000 bps, positive decimal strings with 20 digits/eight fractional places, no unused sizing fields, unknown keys rejected. Optional timer is integer 1–86400 seconds. Market entry pricing cannot combine with budget sizing or a notional cap. A policy edit must leave entries paused; the same atomic save may pause and change the policy, but cannot change a policy and enable entries together. No automatic policy selection.

Policies apply to **followers only**. Host-entered quantities are never scaled by follower settings. Policy changes affect new trade IDs only. The existing source cap remains a live gate; each new snapshot also pins `min(policy.max_source_quantity, current source cap)`. Old open trades keep legacy behavior, including requested-unit exits and no timer, regardless of later selections.

## Durable plans and migration

Persist a per-trade policy snapshot at first receipt, before processing can race a settings edit. Preserve the original immutable source events. Pin pairing fingerprint/public identity, role, verified account/environment and canonical instrument identity. Account binding can complete once using a fresh verified account before any order. Advanced behavior requires a nonempty pairing scope. No credential/token goes in a plan.

One-time policy-schema migration marks all existing trades explicitly legacy without inventing fill costs or source history. A migration marker distinguishes old journals from later missing/corrupt policy records: fail closed and preserve a schema-current journal with missing or contradictory records rather than downgrade it to legacy. Add tables/optional Codable fields; do not drop original evidence. Reads/defaults never enable entries.

Freeze a revision plan containing source event/revision, pinned policy/scope, source quantity, total local target, final buy-price basis and verified multiplier/currency. Persist it before reserving an unknown submission. Reuse it after restart and repeated polls; quotes/settings changes alone cannot increase target. An explicit source replace may create a new revision using the pinned trade policy, after previous working orders are reconciled/terminal. Decreases below purchases cause no new buy and no inferred sale.

Remaining buys subtract cumulative purchases, not current net holdings. Unknown/outstanding orders prevent a new submission. Track actual cumulative average fill price in authoritative per-order evidence; missing cost blocks budget/notional-controlled new buys, but not quantity-proven exits. Sales never replenish entry budget.

For a first entry, source/fixed/ratio/budget arithmetic matches the H.5 fixtures. On explicit budget replace, target = cumulative bought + floor((budget - verified premium spent) / new final unit limit). Do not silently resize fixed/source/ratio targets to fit a cap. Local-target and notional guards reject excess. Cost = all cumulative buy fills × authoritative averages × verified multiplier, plus any reserved/new buy amount. No subtraction for sales; fees are excluded and this is not buying-power approval.

## Broker and dispatch boundary

Advanced modes require fresh metadata binding: account/environment/symbol/asset, USD currency and multiplier 1 for supported US stocks or broker-confirmed size 100 for standard options. USD-only scope is explicit; no FX conversion or adjusted-contract guessing. Verify account currency; US equity/US option asset class defines the supported USD instrument universe, rejecting a contradictory instrument currency if provided. Legacy paths retain existing preflight behavior.

Revalidate instrument/account binding in the broker adapter immediately before the final callback/POST. Do not serialize internal policy binding into the brokerage order body. A checked adapter must not fall back to an unchecked submit method. Unsupported/missing metadata prevents advanced dispatch. Known local refusal remains a retained not-submitted/skipped record; ambiguous POSTs remain unknown and reconcile without replay. Existing lifecycle, OAuth owner, revision, clock/age, pause, source-cap and quantity gates remain at final dispatch.

## Exit goals from complete source intent history

For advanced proportional exits, require an immutable complete per-trade event sequence 1…current: first action enter, consistent identity, no conflicting sequence, and no later entry after cancellation/exit. Preserve/derive the index from the original event ledger. A missing/conflicting history blocks proportional sizing; never guess a source fill count. Missing history does not prevent canceling a freshly reconciled working buy.

The denominator is the latest accepted source entry/replace quantity before exit/cancel. The numerator is the **sum of distinct source exit instruction quantities**, saturated at that denominator. Repeated transport of the same event is not another exit. A new source exit revision is an additional intent, not proof of a source fill. This explicit intent-based definition does not require changing v1 wire envelopes. It does not guarantee matching source positions when brokers reject/fill differently or the source entry partially fills. Explain this in the policy selector; close_tracked is the explicit choice to close all tracked local units on an exit.

Proportional target sold = floor(actual local cumulative bought × numerator / denominator), less actual local cumulative sold, bounded by tracked remaining and broker-available units. Requested mode preserves current per-instruction units minus already sold for that instruction. Close-tracked uses tracked remaining bounded by availability. Entry caps/pause/age never suppress cancel/exit. Unknown outcomes still block new mutations; a zero arithmetic result is not broker terminal proof. Keep rejection/manual-reconciliation behavior and do not auto-retry a rejected exit.

## Optional entry timer

Default is no timer/broker day lifetime. For a selected timer, anchor to monotonic time only after a fresh lookup verifies a live broker order. Preserve acknowledgement/session evidence atomically with broker reconciliation. At timeout, close the entry phase for this trade before attempting cancellation, cancel only the freshly reconciled working buy with its bound broker ID, and retain cancellation uncertainty/retry behavior. Do not sell racing fills or reprice/replace automatically. New source replacements cannot reopen a locally timed-out entry; a new trade ID is required. Exits and source cancels remain available.

Across restart/reconnect, cancel a previously acknowledged timed working buy only after fresh reconciliation, rather than guess elapsed wall-clock downtime. A formerly unknown POST first discovered after restart begins its timer at verified observation. Expose the behavior explicitly: **timed buys cancel on restart/reconnect after reconciliation; racing fills remain holdings**. Timeouts are not guaranteed deadlines during process suspension/network loss. Host orders and legacy open trades never inherit this timer.

## Platform ownership and acceptance

Root owns Python/Windows, common docs, shared JSON fixtures and final CI/commits. Android worker owns `android/` runtime, storage, broker wrappers, controls and tests. iOS worker owns `ios/` runtime, Codable migration, checked REST requests, controls and tests. Do not commit/push in workers or edit another worker's files.

Required regressions: legacy migration/defaults/open trades; policy edit after receipt/before dispatch; first-entry versus replace target freeze; missing scope/metadata/history/cost; option multiplier and dollar math; cumulative purchases after sales; unknown POST restart; final preflight metadata/revision/pause changes; full/proportional exits never use unrelated holdings; duplicate/gap history; timer partial fills/unknown/restart/cancellation uncertainty; follower-only semantics; native lifecycle invalidation. Use fake/intercepted HTTP only, never real credentials, broker orders or Discord posts.
