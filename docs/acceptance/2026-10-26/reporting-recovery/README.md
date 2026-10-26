# R.1–R.3 reporting recovery verification

Accepted source: `a7b332b88b880eb1d23316ce6a306273b9880923`. Seven successful CI runs, actual test counts and copied-report hashes are recorded in [source evidence](source-evidence.json).

| Check | Result |
| --- | --- |
| Full local Python/OAuth suite | 1,033 passed; one optional SDK skip |
| Android | 165 unit tests; APK assembled |
| iOS | 160 native tests; simulator build and unsigned hardware archive |
| Customer UI | Five Android emulator tests, one iOS simulator guide test, Windows intercepted journeys |
| Windows | Desktop checks, portable build and installer install/upgrade/downgrade-refusal/uninstall lifecycle |

R.1 offloads telemetry database reads and writes behind a drained worker boundary and bounds telemetry SQLite write admission. Storage-contention regression verifies that the event loop remains responsive and reporting recovers after the lock is released.

R.2 stores skip reasons with the skip flag in the same transaction. Reporting remains truthful after normal settlement, restart and an injected interruption before settlement. Legacy skipped records without a reason remain explicitly not submitted; no reason is invented from today's clock. Broker order/fill identities and execution permission are unchanged.

R.3 separates in-flight, retryable and successful optional metadata reads on Python/Android/iOS, with monotonic 5–300 second capped backoff and session/account/pair fences. Successful bindings stop retrying. Native report/worker cadence can delay an attempt beyond its earliest eligible time. Cancellation drains the Python read before its broker client is closed and rejects late metadata caching.

The new Python tests were observed failing before implementation. Android's three new tests had behavioral failures before the repair and then passed. Windows has no Xcode; Swift tests were written before the helper, and CI supplied compilation and runtime verification. Independent review found an additional skip-reason crash window; its regression was observed failing, then repaired and reviewed.

The [Sentinel inventory](../../../sentinel-feature-inventory.md) records donor source revisions and limitations. Donor tests were inspected, not run. No other bot was started or modified; no real broker orders or Discord messages were sent. The Supabase function/protocol was unchanged, so this repair required no server deployment.

Independent entries/exits, Echo-style protective/trailing policies, market fallback, separate stock/options allocation and multi-host/cross-broker execution remain future work. Apple signing/enrollment, Webull approval and physical/real broker acceptance remain separate dependencies.
