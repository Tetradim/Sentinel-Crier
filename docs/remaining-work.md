# Remaining work after automated customer acceptance

The approved customer-ease phases E–I have automated source verification. This is acceptance of the implemented app, with the scope and exclusions recorded in each phase report.

## Owner/provider/device work still unpassed

- Webull Connect approval, issued integration details and real authorized integration testing.
- Provider app registrations/credentials, real OAuth consent and activation/deployment of the separately prepared provider service.
- Apple enrollment/signing and an installable signed iPhone/TestFlight candidate. An unsigned archive is not an installation package.
- Real broker/Discord paper receipts and cross-network Host/Follow trials with independent broker-UI reconciliation.
- Actual customer first-success timing and real latency measurements with a defined clock/observer method.
- Physical iPhone suspension/resume, Android background/notification behavior, PC sleep/sign-in/tray behavior and assistive-technology trials.
- Distribution/publisher trust and production operation of the testing relay remain separate from passing CI.

These items have not been silently marked passed, and no new mandatory paper-completion gate has been introduced.

## Designed features requiring further source implementation

H.5 produced a [tested design and non-executing reference](superpowers/specs/2026-10-25-execution-policy-design.md). Live fixed/ratio/budget sizing, separate local notional enforcement, proportional/full-tracked exit selection and timed entry cancellation are not implemented execution features. Activating them requires immutable local trade plans, migration, verified contract/currency data, partial-fill cost/reservation accounting, complete cumulative source-exit history and native conformance. Automatic exit repricing is not an implemented fallback.

The [current settings guide](execution-policies.md) describes available behavior. The [customer acceptance guide](customer-acceptance.md) identifies installable testing routes, recovery, support, automated checks and the deferred real trials.
