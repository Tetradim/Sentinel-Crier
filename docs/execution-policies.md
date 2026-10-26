# Execution settings

## Choose a follower policy

The default remains source-sized orders with requested-unit exits. Existing trades retain their recorded behavior. Optional follower policies apply only to **new trade IDs**, and saving a policy pauses new entries. Review the settings, then explicitly enable entries. Host order quantities are never scaled.

On Windows, connect as a receiver and open **Local execution settings → Follower sizing, exits & timeout**. Android and iOS expose the same choices in their local execution settings. Selecting legacy/default behavior stops applying an advanced policy to future trades; it does not change open trades.

| Entry sizing | Local target |
| --- | --- |
| Source | Source instruction's whole shares/contracts |
| Fixed | Selected whole shares/contracts |
| Ratio | Source quantity × basis points ÷ 10,000, rounded down |
| Budget | Whole units affordable at the final entry limit using the verified contract multiplier |

For example, a $100 budget and a $0.20 standard-option limit produces five contracts: $0.20 × 100 × 5 = $100. On a replacement, already purchased units and verified cumulative cost reduce the remaining budget. Selling units never replenishes the entry budget. Fees are excluded; this is not broker buying-power approval.

The **source quantity cap** rejects larger source instructions. The separate **local target cap** rejects larger calculated targets; it never silently reduces a fixed target. The optional **entry notional cap** limits cumulative purchase premium plus the remaining proposed buy. Budget/notional controls require limit pricing and verified cumulative fill prices. Advanced policies require fresh USD account/instrument metadata and supported multipliers: one for US equities and 100 for standard options. Missing or contradictory evidence blocks submission.

## Exits

| Exit selection | Behavior |
| --- | --- |
| Requested | Requested source units, less units already sold for that instruction |
| Proportional source intents | Cumulative source exit instructions ÷ source entry intent, applied to actual local purchases, rounded down |
| Close tracked on exit | Close all remaining units tracked for this trade when an exit arrives |

Every sale is bounded by local tracked ownership and broker-available holdings. Other account holdings do not expand that ownership. Proportional sizing requires complete, unambiguous source history and saturates at 100%; duplicate delivery does not count twice. It follows **source instructions**, not guaranteed host fills or positions. A rejected or partially filled source order can differ from this ratio. Choose close tracked if an exit should close the locally tracked position in full.

Unknown broker outcomes must reconcile before another order can be sent. Rejected exits are not automatically repriced or blindly retried. Working buys are reconciled and canceled before an invalidating source exit/cancel proceeds, including when proportional history is incomplete.

## Prices, age and cancellation

Exact-limit, bounded-limit and explicitly selected market pricing remain available. Bounded pricing uses the smaller configured slippage allowance. Market orders have no price bound. A local revision plan freezes its target and final price basis before order reservation. A source replacement is a new revision, after prior working orders become terminal. These settings cannot guarantee equal fills or prices between accounts.

**Entry submit age** limits instruction age at submission. It does not cancel working day orders. Pausing entries leaves source cancels/exits active and does not itself cancel existing orders.

An optional **entry timeout** starts after a fresh lookup verifies that the broker accepted a working buy. When it elapses, Crier closes that trade's entry phase and requests cancellation after reconciliation. Later replacements cannot reopen that trade; use a new trade ID. Restart/reconnect cancels previously acknowledged timed working buys after fresh reconciliation. An ambiguous POST first discovered after restart begins its timer on verified observation. Missing acknowledgement evidence cannot renew a known order's lifetime.

Suspension, network loss and cancellation races can delay cancellation. Racing fills remain holdings; timeout never automatically sells them. Without an explicit timeout, broker day-order behavior remains unchanged.

## Contributor checks

The pure `crier/policy_preview.py` reference and 28 shared JSON scenarios remain non-executing arithmetic checks. Runtime plans add durable provenance, cost/history validation, checked metadata, lifecycle and final-dispatch gates. A successful preview is never execution permission.

```powershell
python scripts/check_policy_preview.py
python -m pytest tests/test_execution_policy.py tests/test_policy_broker.py tests/test_policy_preview.py -q
```

See the [runtime contract](superpowers/specs/2026-10-25-live-execution-policy-contract.md) and [remaining real-device/provider work](remaining-work.md).
