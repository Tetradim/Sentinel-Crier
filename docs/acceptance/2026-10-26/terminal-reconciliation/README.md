# Phase K automated verification

Accepted Python source: `a292b06a81d20f0939da99b152e1d970b0c4eb9d`. Native and guide components were verified at `22595df800ac6a27caa394659a3a70d6cf8de207`; their Git objects are identical at the accepted source. The final change affects Python execution-health reporting and its tests. The [evidence report](source-evidence.json) records eight successful runs, component identities, actual test counts and copied-report checksums.

| Check | Result |
| --- | --- |
| Local Python / Windows OAuth matrix | 990 passed, one optional Webull SDK skip |
| Linux Python 3.11 / 3.12 OAuth matrix | 955 passed, 36 headless/optional skips each |
| Default Linux backend matrix | 886 passed, 38 headless/optional skips each |
| Android unit / package | 153 tests; debug APK built |
| Android emulator | Five UI/persistence tests |
| iOS native | 147 tests |
| iOS simulator UI | One test traversing all three practice guides |
| iOS packaging | Simulator build and unsigned arm64 hardware archive |
| Windows | Portable smoke and install/upgrade/downgrade-refusal/uninstall lifecycle |

The initial Python regression showed a terminal buy lookup returning no evidence while an exit still submitted using cached fills. Native tests also reproduced terminal-cache authorization. The fix refreshes broker-backed terminal records before another order, persists corrected cumulative fill costs, blocks missing/malformed proof and resumes once without duplicate submission.

Independent review added final cancellation lifecycle/owner checks, per-order failure collection, cancellation-only iOS resume recovery, explicit no-POST handling, no historical polling after resolved instructions, and accurate blocked execution health. The old iOS HTTP-refusal upgrade requires both the exact old writer shape and matching durable rejection diagnostics; unknown submissions and unproven records remain blocked. Original order and timeline evidence are retained.

Copied reports:

- [Windows installer lifecycle](windows-installer-acceptance.json)
- [iOS unsigned archive validation](ios-unsigned-archive-validation.json)
- [Windows offline practice journeys](windows-journey-report.json)

The Windows guide report is attributed to its earlier verified component commit. Offline timings are automation durations, not real customer setup time or cross-device latency. The iOS archive remains unsigned and not installable. Real broker/Discord, provider activation, Apple signing, cross-network and physical-device acceptance remain [unpassed](../../../remaining-work.md). No real orders or Discord messages were sent in this phase.
