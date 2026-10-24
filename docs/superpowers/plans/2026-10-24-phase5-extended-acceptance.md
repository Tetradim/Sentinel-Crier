# Phase 5 extended acceptance

**Goal:** Close the executable acceptance gaps left by manual engine ticking and package-only Windows checks, without treating simulated brokerage evidence as actual account acceptance.

## Work

- [x] Add concurrent host/follower publish, receive and execute-loop tests. Hold the host's broker response, prove the follower can submit/cancel independently, then replay durable journals after restart without duplicate broker requests.
- [x] Verify actual Alpaca fill normalization through durable Discord rendering/delivery: incremental option quantities, exact premiums/costs, timestamps, provenance, replay, retries and ambiguous-send quarantine.
- [ ] Add a Windows installer acceptance helper guarded to fresh ephemeral CI runners. Install, upgrade using an acceptance-only higher installer version, reject downgrade, uninstall and verify synthetic unresolved journal plus DPAPI credential retention.
- [ ] Run complete Python tests and independent review. Execute real installer acceptance in disposable Windows CI and retain its redacted report.
- [ ] Update the Phase 5 result matrix, commit/push directly to main, and identify the remaining physical/account-dependent requirements.

## Boundaries

No live brokerage, real Discord destination or customer's Crier installation is used. Windows installation runs only in an isolated CI runner and does not replace customer hardware acceptance. The acceptance-only upgrade installer uses the same candidate program files under a higher installer version; it does not prove future application schema migrations or constitute a new release. Native mobile installation, real broker UI comparisons, actual Discord channel rendering and cross-network phone trials remain separately deferred/unverified.
