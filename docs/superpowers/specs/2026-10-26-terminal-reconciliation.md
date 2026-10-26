# Fresh reconciliation before another broker order

Phase K closes a reproduced stale-evidence gap after Phase J. Work directly on main under standing approval; no real broker/Discord actions, no policy expansion or wire change.

Before authorizing a new entry, replacement or exit for a tracked trade, freshly look up every prior broker-backed mutation by its deterministic client ID, including filled/canceled/expired/replaced/rejected terminal records. Validate the same account, symbol, side, broker ID, submitted quantity, status and nondecreasing cumulative whole-unit fill evidence. Persist any authoritative updated average/quantity before deriving cumulative purchases, spending or sell due. A missing/unavailable/malformed lookup cannot authorize another order using cached terminal evidence.

Do not query fabricated local no-POST dispositions: Python skipped or definitively rejected rows with no broker ID and zero fills; iOS explicit notSubmitted mutations; Android explicit superseded/known-local-refusal markers. Such dispositions never prove broker fills. Missing records must not be mistaken for locally refused orders. Unknown actual POSTs still require reconciliation and must never blindly repeat.

Preserve cancellation identity checks, cooldown/unknown handling, checked dispatch, policy/price snapshots, quantity/cost limits, role/ownership fencing and source invalidation. Broker evidence becoming available later resumes the same durable instruction without a duplicate buy or sale. A terminal observation does not grant permission to auto-retry a rejected/canceled exit. Metadata and broker availability checks still apply.

Completed trades may remain idle when there is no new instruction. Do not start polling all historical settled trades forever or infer an unrequested new trade. At a new execution boundary, terminal cache is not a substitute for fresh proof. On reconnect, any work that may submit must perform this same validation.

Required tests use intercepted/fake brokerage only: terminal buy unavailable blocks replacement/exit and recovery submits once; terminal fill/average changed before a new source revision is consumed fresh; changed ID/symbol/side/quantity, decreasing fills and invalid average reject; terminal sell unavailable cannot authorize another sale; local known-no-POST skips need no lookup; unknown real POST remains blocked; legacy and advanced paths; timer closure/cancellation semantics remain intact.

Root owns Python/Windows, docs and integration. Native workers own Android and iOS respectively, with no commits/push. New tests should fail first against the existing code, then verify the focused fix. Record source-bound native/packaging CI without claiming physical acceptance.
