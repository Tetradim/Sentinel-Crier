# Recovery assistant (Windows account bank)

Open **Account ID bank → Recovery assistant** on the selected connection. The initial view uses local evidence and explicitly does not claim a broker check. It lists recorded holdings, pending quantities, unknown outcomes and preservation steps.

**Pause entries and check broker evidence** requires a connected managed account. It pauses new entries across connected routes using the same account, verifies the account, looks up unresolved orders by their original client IDs, and compares positions with the existing bank. The check is serialized with account operations and drains before the selected connection closes.

This action never posts or cancels an order, deletes IDs, releases an unknown reservation, reassigns holdings, clears contradictory evidence or resumes entries. Existing reconciliation rules can clear an inventory-only discrepancy when authoritative inventory again matches the unchanged ledger. An unresolved result needs broker investigation. Network errors remain errors rather than a successful check.

This is the first Windows integration. Broker-side comparisons are enforced by reconciliation; the current screen shows ledger quantities and an overall result, not a detailed side-by-side broker snapshot. Per-order guided repairs, mobile recovery views and the Webull-inspired iOS redesign remain unfinished. Existing broker orders and ongoing exits are not canceled by pausing entries.
