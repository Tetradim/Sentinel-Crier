# Remaining work after automated customer acceptance

The approved customer-ease phases E–I, live-policy phase J, reconciliation phase K and push/dashboard phase L have automated source verification. This is acceptance of the implemented source scope, with exclusions recorded in each phase report.

## Owner/provider/device work still unpassed

Phase L's [completed plan](superpowers/plans/2026-10-26-push-dashboard.md) and [accepted evidence](acceptance/2026-10-26/push-dashboard/source-evidence.json) record push delivery, the read-only dashboard, hosted deployment and an isolated synthetic probe. See the [usage guide](push-dashboard.md). The following external work remains unpassed:

- Webull Connect approval, issued integration details and real authorized integration testing.
- The [candidate Webull iPhone → Alpaca-paper Windows route](webull-iphone-host.md) now has native host and authenticated gateway/ledger code. Its [authorization runtime and deployable service](webull-authorization-deployment.md) are now composed. It still needs the approved account/contract/order resource adapter, operator activation and real sandbox acceptance. This is a specific single-host route, not completion of deferred D.1.
- Provider app registrations/credentials, real OAuth consent and activation/deployment of the separately prepared provider service.
- Apple enrollment/signing and an installable signed iPhone/TestFlight candidate. An unsigned archive is not an installation package.
- Real broker/Discord paper receipts and cross-network Host/Follow trials with independent broker-UI reconciliation.
- Actual customer first-success timing and real latency measurements with a defined clock/observer method.
- Physical iPhone suspension/resume, Android background/notification behavior, PC sleep/sign-in/tray behavior and assistive-technology trials.
- Distribution/publisher trust and production operation of the testing relay remain separate from passing CI.

These items have not been silently marked passed, and no new mandatory paper-completion gate has been introduced.

## Additional autonomous hardening

Windows 0.3.0 now includes signed release discovery/download, private recovery
snapshots, profile/protocol/source compatibility checks and installer handoff after
normal worker shutdown. Release authority is provisioned in protected local storage
and encrypted Actions secrets. See [update operations](customer-updates.md).
Windows 0.3.0 is [published](https://github.com/Tetradim/Sentinel-Crier/releases/tag/v0.3.0)
with [accepted verification](acceptance/2026-10-27/customer-updates/README.md).
Future releases still require deliberate publication; Microsoft publisher reputation
and physical acceptance remain unverified. Apple distribution remains deferred.

The [Webull authorization service assembly](webull-authorization-deployment.md) now composes browser consent, encrypted custody/refresh, local revocation, request admission and a deployable Edge entry point. The approved account/contract/order adapter and actual activation remain unfinished.

[Windows unattended diagnostics](unattended-diagnostics.md) add bounded background technical logs and a local support bundle with packaged source metadata. Independent remote outage notification, real unattended recovery trials and automatic restart policy remain separate; no automatic trading restart was enabled.

[Accepted authorization and Windows diagnostics evidence](acceptance/2026-10-26/customer-handoff-ops/README.md) records the implementation revisions, automated checks and exclusions. These changes do not activate Webull trading or establish customer-ready handoff.

[October 27 Webull HTTP boundary verification](acceptance/2026-10-27/webull-response-bounds/README.md) additionally records bounded streaming replies, prompt body cancellation and enforced resource deadlines. This hardens the existing transports without enabling a trading adapter.

[Tracked source inventory reservations](acceptance/2026-10-27/webull-owned-quantity/README.md) now serialize competing sales against recorded buy fills and retain uncertain reservations. Contradictory evidence blocks new orders in the exact scope, including after a revision race. Existing external holdings/orders, broker-side long-only enforcement and a reviewed authoritative recovery mechanism remain outside this guard and are still required for the approved trading adapter.

## Deferred future enhancements

The [future-scope register](future-scope.md) expands D.1/D.2 with candidate controls, recurring stock-card ideas, accounting requirements and research/acceptance work. It does not activate those features.

- **D.1 — Multiple Hosts, Connections, and Cross-Broker Copying:** one app with multiple simultaneous host subscriptions and brokerage sessions; explicit host-to-account routing, including Dave on Alpaca to Carol on Webull, and different hosts assigned to Tradier, Webull and Alpaca accounts. Preserve per-host ownership, shared-account reservations, scoped idempotency, account/environment isolation and loop prevention. Research covers direct OAuth/API connections, broker stream limits and optional middleware. [Research, dependencies and future work](deferred/multi-host-cross-broker.md). Deferred by owner request; not implemented or activated, and outside the completed E–L phase scopes.
- **D.2 — Independent Trading Policies and Stock/Option Allocation:** requested inventory of optional independent entry/exit authority, Echo-style coordinated trailing/stops/profit stages, cancel/reconcile/market fallback, and separate stock/options funding pools. [Sentinel source inventory and candidate controls](sentinel-feature-inventory.md). Proposals only; no independent strategy or fallback was enabled by the inventory. D.1 remains separately deferred.

## Reviewed reporting defects — repaired

The [October 26 review](reviews/2026-10-26-copy-trading-comparison.md) identified **R.1** blocking telemetry database waits, **R.2** incorrect skipped-entry reporting and **R.3** one-attempt metadata suppression. Source `a7b332b` repairs all three, including a separately reproduced skip-reason crash window. [Accepted verification](acceptance/2026-10-26/reporting-recovery/source-evidence.json) records 1,033 full Python tests/one optional SDK skip, 165 Android tests, 160 iOS tests, UI/build and Windows installer checks. D.1 is still deferred, and D.2 is an inventory rather than active trading functionality.

## Live follower policies verified

Phase J implements H.5's optional fixed/ratio/budget sizing, separate local quantity/notional enforcement, proportional source-intent/full-tracked exits and acknowledged entry timeouts on Python/Windows, Android and iOS. Durable receipt snapshots, frozen revision plans, verified metadata/costs and complete proportional history preserve legacy defaults and prevent settings edits from changing old trades. The [completed implementation plan](superpowers/plans/2026-10-25-live-execution-policy.md) and [accepted evidence](acceptance/2026-10-25/live-execution-policy/source-evidence.json) record source verification. Automatic exit repricing remains outside this scope.

The [current settings guide](execution-policies.md) describes available behavior. The [customer acceptance guide](customer-acceptance.md) identifies installable testing routes, recovery, support, automated checks and the deferred real trials.

## Reconciliation hardening verified

The [completed Phase K plan](superpowers/plans/2026-10-26-terminal-reconciliation.md) adds fresh terminal-order evidence at execution boundaries. It prevents unavailable or corrected cached fills from authorizing another order, while retaining independently verified cancellations and stopping resolved historical polling. The [accepted evidence](acceptance/2026-10-26/terminal-reconciliation/source-evidence.json) records full/native/platform/package verification. Phases E through L retain their recorded acceptance scope; the subsequent reporting repairs have their own accepted verification above. D.1 and D.2 remain future work. The owner/provider/device items remain unpassed.
