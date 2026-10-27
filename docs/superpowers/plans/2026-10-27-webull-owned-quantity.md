# Webull source-owned quantity reservations

Continue the approved iPhone Webull → Windows Alpaca-paper route. Before dispatch, the private durable ledger must refuse overlapping Crier sales that exceed verified Crier buy fills for the exact owner, environment, account, asset and canonical symbol. A position snapshot alone cannot serialize competing sells.

Design: serialize reservation decisions by locking the durable row for that exact quantity scope under READ COMMITTED. The same row stores the reconciliation block, avoiding a separate advisory-lock namespace. Derive owned quantity from accepted cumulative buy fills. Every uncertain/working sell reserves its entire requested quantity; a terminal sale consumes its cumulative fills. An authoritative cancellation releases only its unfilled remainder. Duplicate client IDs return the original reservation. Insufficient tracked quantity is a typed refusal before dispatch. Late contradictory terminal fill corrections block new orders in the affected scope until a future reviewed recovery mechanism exists; never silently increase a released reservation after another sale may have consumed it.

This guard protects Crier-tracked inventory, not all external brokerage activity. It does not replace fresh provider validation, broker-enforced sell-to-close/reduction, pending external-order handling or actual integration acceptance. Existing holdings bought outside Crier are not imported. No operator reset or guessed broker endpoint is added.

- [x] Add failing SQL and gateway/RPC regressions for overlapping sales, uncertain reservations, partial cancellation, exact scope, idempotency and terminal correction fencing.
- [x] Implement private quantity-scope locks/fences, atomic reservation refusal and typed gateway handling; preserve service-only permissions.
- [ ] Add real PostgreSQL concurrent competing-sale acceptance and run Deno, PGlite/integrated and CI checks.
- [ ] Record source evidence, update remaining work and commit/push main without activating Webull trading.
