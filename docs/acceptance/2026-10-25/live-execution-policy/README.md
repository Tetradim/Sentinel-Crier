# Phase J automated verification

Accepted application source: `2f9e2387b8455b220cbd6cf643d75bb020b3e842`. The [source evidence](source-evidence.json) records eight successful CI runs, component identities, test results and copied-report checksums. Android packaging/unit tests ran at `282b717`; its Android Git tree is identical to the accepted source. Final emulator persistence tests ran at the accepted source.

| Check | Result |
| --- | --- |
| Local Python / Windows OAuth matrix | 980 passed, one optional Webull SDK skip |
| Linux Python 3.11 and 3.12 OAuth matrix | 945 passed, 36 expected headless/optional skips each |
| Default Linux backend | 876 passed, 38 headless/optional skips |
| Android | 131 unit tests and debug APK build |
| Android emulator | Five tests, including three journal/vault persistence tests |
| iOS native | 137 tests, including fractional budget and long fill-average regressions |
| iOS simulator UI | One test traversing all three optional practice guides |
| iOS packaging | Simulator build and unsigned arm64 hardware archive validation |
| Windows | Portable package smoke; install, upgrade, downgrade refusal, uninstall and retained synthetic journal/credential evidence |

The runtime follows receipt-pinned policies and frozen revision plans. Fault checks cover missing markers/plans, mutated targets/prices, missing/nonpositive costs, authoritative averages, source-history gaps, final metadata/pause/lifecycle changes, unknown submissions and timer acknowledgement loss. Source cancellation and quantity-proven exits remain available when history/cost evidence blocks a new entry.

Native CI exposed a fractional-Decimal integer-conversion error and a test that inspected transient text after disconnect. Both were repaired; earlier failed runs are not counted as accepted evidence. Fill costs now preserve representable weighted averages rather than apply the policy-input eight-decimal limit, and arithmetic precision loss blocks an entry.

Copied reports:

- [Windows installer lifecycle](windows-installer-acceptance.json)
- [iOS unsigned archive](ios-unsigned-archive-validation.json)
- [Windows offline practice journeys](windows-journey-report.json)

Offline journey timings are automation durations, not customer setup time or cross-device latency. Simulator/emulator and ephemeral Windows results do not establish physical-device behavior. The unsigned iOS archive is not installable. Real provider activation, Apple signing, broker/Discord receipts, cross-network and physical acceptance remain [unpassed](../../../remaining-work.md). No real broker orders or Discord messages were sent by this phase.
