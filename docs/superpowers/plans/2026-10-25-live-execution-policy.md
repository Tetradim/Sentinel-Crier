# Live follower policies implementation plan

Execute the H.5 runtime contract directly on main under standing authorization. Preserve legacy behavior and all broker reconciliation gates; no real orders/messages or owner-dependent activation.

- [x] J.1 Durable policy snapshots/revision plans, migration and authoritative cost evidence; strict shared configuration and history validation.
- [x] J.2 Python/Windows checked execution, broker metadata, explicit paused policy selection and visible local targets.
- [x] J.3 Android durable plans, metadata-checked execution, explicit settings and regressions.
- [x] J.4 iOS Codable migration/plans, metadata/lifecycle dispatch fencing, explicit settings and regressions.
- [x] J.5 Proportional intent/full-tracked exits and optional monotonic timer/restart cancellation with complete history and preserved unknown outcomes on all platforms.
- [ ] J.6 Cross-platform fixtures, fault/restart/preflight regressions, full/native/UI/packaging CI, current feature/remaining-work documentation and source-bound evidence; direct commit/push.

The [runtime contract](../specs/2026-10-25-live-execution-policy-contract.md) is the common boundary for parallel platform work. No separate executor or source-wire mutation is introduced. Provider/signing/physical gates stay deferred.

Local source verification: 978 Python tests passed with one optional Webull SDK skip; Android production/test sources compiled with 130 offline JUnit tests passed. Native iOS, emulator UI, cross-platform matrix and Windows packaging still require the source-bound CI run. Review regressions include missing schema markers, altered target/price plans, missing prior-plan references, stale/missing/nonpositive costs and acknowledgement evidence loss.
