# Live follower policies implementation plan

Execute the H.5 runtime contract directly on main under standing authorization. Preserve legacy behavior and all broker reconciliation gates; no real orders/messages or owner-dependent activation.

- [x] J.1 Durable policy snapshots/revision plans, migration and authoritative cost evidence; strict shared configuration and history validation.
- [x] J.2 Python/Windows checked execution, broker metadata, explicit paused policy selection and visible local targets.
- [x] J.3 Android durable plans, metadata-checked execution, explicit settings and regressions.
- [x] J.4 iOS Codable migration/plans, metadata/lifecycle dispatch fencing, explicit settings and regressions.
- [x] J.5 Proportional intent/full-tracked exits and optional monotonic timer/restart cancellation with complete history and preserved unknown outcomes on all platforms.
- [x] J.6 Cross-platform fixtures, fault/restart/preflight regressions, full/native/UI/packaging CI, current feature/remaining-work documentation and source-bound evidence; direct commit/push.

The [runtime contract](../specs/2026-10-25-live-execution-policy-contract.md) is the common boundary for parallel platform work. No separate executor or source-wire mutation is introduced. Provider/signing/physical gates stay deferred.

Final verification: **980 local Python tests passed / one optional Webull SDK skip**, **131 Android unit tests**, **137 iOS native tests**, **five Android emulator tests**, **one iOS UI test**, Windows/Linux Python matrices, native/debug/unsigned archive builds, Windows portable smoke and installer lifecycle checks. The [source-bound evidence](../../acceptance/2026-10-25/live-execution-policy/source-evidence.json) records source `2f9e238`, accepted runs and the byte-identical Android component verified at `282b717`.

Review and native-CI regressions include missing schema markers, altered target/price plans, missing prior-plan references, stale/missing/nonpositive costs, acknowledgement evidence loss, fractional-budget flooring and exact broker averages beyond eight decimal places. Earlier failed native runs were repaired and are not accepted evidence.

Phase J's code and automated verification scope is complete. [Remaining work](../../remaining-work.md) is provider activation, signing/distribution, real broker/Discord/cross-network and physical-device acceptance. No real orders or Discord messages were sent in this phase.
