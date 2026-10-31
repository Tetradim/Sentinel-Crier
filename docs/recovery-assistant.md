# Recovery assistant (Windows account bank)

Open **Account ID bank → Recovery assistant** on the selected connection. The initial view uses local evidence and explicitly does not claim a broker check. It lists recorded holdings, pending quantities, unknown outcomes and preservation steps.

**Pause entries and check broker evidence** requires a connected managed account. It pauses new entries across connected routes using the same account, verifies the account, looks up unresolved orders by their original client IDs, and compares positions with the existing bank. The check is serialized with account operations and drains before the selected connection closes.

This action never posts or cancels an order, deletes IDs, releases an unknown reservation, reassigns holdings, clears contradictory evidence or resumes entries. Existing reconciliation rules can clear an inventory-only discrepancy when authoritative inventory again matches the unchanged ledger. An unresolved result needs broker investigation. Network errors remain errors rather than a successful check.

The fresh check includes a timestamped position comparison: symbol, host-owned quantity, separately recorded external baseline, expected total, actual broker quantity and difference. A difference remains unresolved; it never changes host ownership to make the numbers match. Network or identity failures do not produce a successful check. The snapshot is historical evidence, not a continuous position feed.

Per-order guided repairs and mobile recovery views remain unfinished. The iOS shell has an initial dark, compact trading-workspace header with an environment badge and existing bottom navigation; detailed chart, order-ticket and position-screen redesign remains pending native visual acceptance. Existing broker orders and ongoing exits are not canceled by pausing entries.
