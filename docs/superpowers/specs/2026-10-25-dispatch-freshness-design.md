# H.3 dispatch freshness and transport review

Use the approved H.3 scope without changing sizing, price tolerance, order lifetime or broker reconciliation policy.

Each running executor anchors its entry clock to wall time and a monotonic clock. Effective entry time cannot move backwards. A wall/monotonic discrepancy greater than five seconds, invalid clock sample or backwards monotonic time defers new entries with a visible fixed reason. Check again immediately before dispatch. Explicit reconnect creates a new anchor; cancellation, exits and authoritative broker reconciliation remain available. This detects local clock discontinuities, not static offsets between devices: automatic device time remains an operating prerequisite. Existing relay diagnostic offsets are not silently promoted into an execution-time authority.

Keep account/instrument checks required for identity and current trade authorization; do not add cross-order account/asset caching. Remove only the immediately repeated iOS account read during initial read-only refresh, using the account just verified in the same connection attempt. Later refreshes and mutation preflights still verify normally.

For iOS intent submissions, check current API/lifecycle identity, revision, paused/invalidated state, age, expiry and quantity again on the main actor immediately before URLSession dispatch. A positive pre-send refusal is a retained local not-submitted mutation, not an unknown broker order or a broker rejection. Such records do not authorize a retry of an ambiguous POST. Retain unknown POST reconciliation and all holding/cumulative-fill checks.

Classify HTTPX ConnectError, ConnectTimeout and PoolTimeout as pre-send failures with the existing bounded retry policy. ReadTimeout, WriteTimeout, protocol failures and ambiguous HTTP responses remain uncertain and are not automatically replayed. Never report delivery without a valid acknowledged message ID.

Compare the current pricing mode and configured slippage against the settings used to form an order at final dispatch. A change refuses the unsent entry or exit with `pricing_changed`; it does not reprice or replay the order. Existing host defaults remain unchanged. Android's running service uses `elapsedRealtime`, which includes device sleep, for entry-clock continuity. On loading the iOS journal, reject a contradictory local not-submitted marker that also contains a broker order or cancellation attempt.

Tests inject time, broker preflight delays, revisions and HTTP responses. Cover clock changes before/during preflight, deferred versus skipped decisions, unchanged cancel/exit behavior, initial account-read counts, final iOS refusal and unknown POST persistence. No real order, provider login, message or deployment is needed.
