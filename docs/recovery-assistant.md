# Recovery assistant (Windows account bank)

Open **Account ID bank → Recovery assistant** on the selected connection. The initial view uses local evidence and explicitly does not claim a broker check. It lists recorded holdings, pending quantities, unknown outcomes and preservation steps.

**Pause entries and check broker evidence** requires a connected managed account. It pauses new entries across connected routes using the same account, verifies the account, looks up unresolved orders by their original client IDs, and compares positions with the existing bank. The check is serialized with account operations and drains before the selected connection closes.

This action never posts or cancels an order, deletes IDs, releases an unknown reservation, reassigns holdings, clears contradictory evidence or resumes entries. Existing reconciliation rules can clear an inventory-only discrepancy when authoritative inventory again matches the unchanged ledger. An unresolved result needs broker investigation. Network errors remain errors rather than a successful check.

The fresh check includes a timestamped position comparison: symbol, host-owned quantity, separately recorded external baseline, expected total, actual broker quantity and difference. A difference remains unresolved; it never changes host ownership to make the numbers match. Network or identity failures do not produce a successful check. The snapshot is historical evidence, not a continuous position feed.

Per-order guided repairs and mobile recovery views remain unfinished. The iOS shell has an initial dark, compact trading-workspace header with an environment badge and existing bottom navigation; detailed chart, order-ticket and position-screen redesign remains pending native visual acceptance. Existing broker orders and ongoing exits are not canceled by pausing entries.

Recovery dialogs are tied to the connection selected when opened. Switching connections requires reopening the assistant before running its check. The comparison table has a regression test for visible broker differences and refusal to dispatch against a different selected route.

The iOS Positions screen now uses a compact dark list, symbol search, separate market-value and quantity/average columns, and explicit last-loaded-snapshot empty-state guidance. These values come from the existing broker model; the presentation does not add simulated prices, P&L or execution actions. Native compilation and visual acceptance for each revision are separate checks.

Order-ticket presentation is tracked in [iOS trading UI](ios-trading-ui.md); mobile recovery remains a distinct unfinished integration, not an inference from Windows support.

## iOS observational entry point

Home → Advanced and recovery → Recovery assistant, or Positions → Recovery, opens the native local-evidence view. It shows the selected environment/account, workspace update timestamp, loaded manual order client IDs and broker IDs/status/fill counts, and links to existing paired execution diagnostics. No records loaded is explicitly not proof of an empty broker account. Paired diagnostics observe their controller so newly recorded trades can appear while the screen remains open.

The mobile view contains no order, cancellation, retry or reset action. Its dedicated read-only check verifies the connected account, reads positions and looks up the latest 100 saved manual orders by original client ID. It validates each returned order against its saved ticket and rejects fractional or excessive filled quantities. A 404 remains unresolved. Account/session changes discard the result. Network failures are shown as failures, not verification.

The completed-check timestamp and requested/local/broker order states are shown together; positions are displayed separately because they contain all account activity. These are sequential reads, not an atomic broker snapshot. The check does not write broker evidence into the execution journal, reconcile paired trades, assign ownership or resume entries. The general workspace refresh is not reused. Native shared-account ledger parity, automatic/manual journal repair workflows and physical visual/lifecycle acceptance remain unfinished. Native compilation and the added evidence-validation tests run through the macOS CI workflow.
