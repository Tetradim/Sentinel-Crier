# Sentinel source reuse and reporting-recovery repairs

Scope authorized October 26, 2026: inspect Sentinel bots, repair reviewed R.1–R.3, and record candidate independent trading/multi-broker/asset-allocation features. No independent strategy, stop, market fallback or multiple-host runtime is enabled here.

Implementation source: `a7b332b`. Donor evidence and limitations: [Sentinel feature inventory](../../sentinel-feature-inventory.md).

- [x] Inspect Echo's awaited persistence, reconciliation outcomes, coordinated trailing and exit lifecycle; inspect the other Sentinel code rather than infer support from registry names.
- [x] Reproduce PC storage contention, skipped-reason loss and transient metadata suppression with failing tests before implementation.
- [x] R.1: isolate all async reporter database work behind a drained background boundary, use short retryable telemetry write admission, and test loop responsiveness plus recovery.
- [x] R.2: preserve skipped flag and decision reason atomically; map existing report enums after settlement/restart. Preserve return shapes, broker evidence and execution permissions.
- [x] R.3: implement optional read-only metadata backoff on Python/Android/iOS, retain successful bindings, fence late callbacks, cancel/drain work on disconnect and test retry readiness/cap/scope.
- [x] Independently review the Python repairs. Reproduce and fix the additional interruption window between setting skipped and persisting its reason.
- [x] Record D.2 candidate authority modes, Echo's trailing source and safe reuse limits, market-fallback lifecycle and distinct stock/options funding requirements. Keep D.1 separately deferred.
- [x] Complete full/native/UI/package verification and record source-bound evidence; update review disposition and remaining work.

Verification includes the full local Python/OAuth suite, focused red/green regressions, Android unit/build/UI checks, iOS compilation/native/UI tests and Windows packaging/lifecycle. Windows has no local Xcode; Swift tests were written first and require CI execution. Donor tests are source references only; no live donor bot or broker request was used.

Completed: 1,033 full local Python tests passed with one optional SDK skip; Android passed 165 unit tests and five emulator checks; iOS passed 160 native tests and one simulator guide test. Native builds, unsigned iPhone archive, Windows desktop/portable/installer checks and seven source-matched CI runs passed. [Evidence](../../acceptance/2026-10-26/reporting-recovery/source-evidence.json).
