# Remaining work after automated customer acceptance

The approved customer-ease phases E–I, live-policy phase J, reconciliation phase K and push/dashboard phase L have automated source verification. This is acceptance of the implemented source scope, with exclusions recorded in each phase report.

## Owner/provider/device work still unpassed

Phase L's [completed plan](superpowers/plans/2026-10-26-push-dashboard.md) and [accepted evidence](acceptance/2026-10-26/push-dashboard/source-evidence.json) record push delivery, the read-only dashboard, hosted deployment and an isolated synthetic probe. See the [usage guide](push-dashboard.md). The following external work remains unpassed:

- Webull Connect approval, issued integration details and real authorized integration testing.
- Provider app registrations/credentials, real OAuth consent and activation/deployment of the separately prepared provider service.
- Apple enrollment/signing and an installable signed iPhone/TestFlight candidate. An unsigned archive is not an installation package.
- Real broker/Discord paper receipts and cross-network Host/Follow trials with independent broker-UI reconciliation.
- Actual customer first-success timing and real latency measurements with a defined clock/observer method.
- Physical iPhone suspension/resume, Android background/notification behavior, PC sleep/sign-in/tray behavior and assistive-technology trials.
- Distribution/publisher trust and production operation of the testing relay remain separate from passing CI.

These items have not been silently marked passed, and no new mandatory paper-completion gate has been introduced.

## Deferred future enhancements

- **D.1 — Multiple Hosts, Connections, and Cross-Broker Copying:** one app with multiple simultaneous host subscriptions and brokerage sessions; explicit host-to-account routing, including Dave on Alpaca to Carol on Webull, and different hosts assigned to Tradier, Webull and Alpaca accounts. Preserve per-host ownership, shared-account reservations, scoped idempotency, account/environment isolation and loop prevention. Research covers direct OAuth/API connections, broker stream limits and optional middleware. [Research, dependencies and future work](deferred/multi-host-cross-broker.md). Deferred by owner request; not implemented or activated, and outside the completed E–L phase scopes.
- **D.2 — Independent Trading Policies and Stock/Option Allocation:** requested inventory of optional independent entry/exit authority, Echo-style coordinated trailing/stops/profit stages, cancel/reconcile/market fallback, and separate stock/options funding pools. [Sentinel source inventory and candidate controls](sentinel-feature-inventory.md). Proposals only; no independent strategy or fallback was enabled by the inventory. D.1 remains separately deferred.

## Reviewed reporting defects — repaired

The [October 26 review](reviews/2026-10-26-copy-trading-comparison.md) identified **R.1** blocking telemetry database waits, **R.2** incorrect skipped-entry reporting and **R.3** one-attempt metadata suppression. Source `a7b332b` repairs all three, including a separately reproduced skip-reason crash window. [Accepted verification](acceptance/2026-10-26/reporting-recovery/source-evidence.json) records 1,033 full Python tests/one optional SDK skip, 165 Android tests, 160 iOS tests, UI/build and Windows installer checks. D.1 is still deferred, and D.2 is an inventory rather than active trading functionality.

## Live follower policies verified

Phase J implements H.5's optional fixed/ratio/budget sizing, separate local quantity/notional enforcement, proportional source-intent/full-tracked exits and acknowledged entry timeouts on Python/Windows, Android and iOS. Durable receipt snapshots, frozen revision plans, verified metadata/costs and complete proportional history preserve legacy defaults and prevent settings edits from changing old trades. The [completed implementation plan](superpowers/plans/2026-10-25-live-execution-policy.md) and [accepted evidence](acceptance/2026-10-25/live-execution-policy/source-evidence.json) record source verification. Automatic exit repricing remains outside this scope.

The [current settings guide](execution-policies.md) describes available behavior. The [customer acceptance guide](customer-acceptance.md) identifies installable testing routes, recovery, support, automated checks and the deferred real trials.

## Reconciliation hardening verified

The [completed Phase K plan](superpowers/plans/2026-10-26-terminal-reconciliation.md) adds fresh terminal-order evidence at execution boundaries. It prevents unavailable or corrected cached fills from authorizing another order, while retaining independently verified cancellations and stopping resolved historical polling. The [accepted evidence](acceptance/2026-10-26/terminal-reconciliation/source-evidence.json) records full/native/platform/package verification. Phases E through L retain their recorded acceptance scope; the subsequent reporting repairs have their own accepted verification above. D.1 and D.2 remain future work. The owner/provider/device items remain unpassed.
