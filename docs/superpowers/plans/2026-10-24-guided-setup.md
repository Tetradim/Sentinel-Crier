# Phase F — Cross-platform guided setup

> **For agentic workers:** Use subagent-driven-development for independent platform tasks, then review integration and verification before committing directly to main.

**Goal:** Finish the approved purpose-driven setup design without changing pricing, order reconciliation, or live authorization policy.

**Baseline:** `8f62bff`. Phase F.1 already supplies Windows alerts-only monitoring with isolated credentials, cursor and outbox. Phase E controls and A–D offline server work remain intact.

**Design:** Keep a single app with Alerts, Trade/share and Follow routes. Saving a purpose only selects navigation. Account/environment verification, Discord preview, explicit test result and permission to publish remain separate evidence. Clear readiness when relevant configuration changes, disconnects or the process restarts; retained settings are reusable, not proof of a current connection. No automatic tests, connects, enables or trade submissions on first launch. A test is a labelled synthetic message; its acknowledgement never represents a fill. Do not make successful test delivery or paper practice a new mandatory live-trading gate. Inactive journey controls must not mutate another profile.

## Tasks

- [x] F.2 Android: add purpose selection and a guided account/Discord path. Alerts-only must verify/read Alpaca without Host/Receive, relay or an order engine, use separate encrypted configuration and durable account/environment-scoped state, and preserve baseline/outbox uncertainty rules. Expose foreground/background limitations. Test setup transitions, restart, read-only HTTP boundaries and fill evidence. Keep existing Trade/Follow recovery available.
- [x] F.3 iOS: integrate purpose-driven setup with the existing native broker/fill publisher. Show account verification, configuration/preview/test and delivery permission honestly. Alerts-only must not activate a saved mirroring engine or require a channel. Preserve journals, Keychain identity, explicit live permission and foreground lifecycle. Test readiness invalidation and no execution on the Alerts path.
- [x] F.4 Windows: add guided preview/test/enable readiness to the F.1 path, retaining explicit controls and destination-preservation constraints. Scope evidence to active account/destination; clear stale asynchronous completions. Test incomplete setup, reconnect, destination changes and failed/uncertain test acknowledgements using mocked workers/HTTP only.
- [x] F.5 Review each platform against the above design, fix findings, run complete Python and native compilation/test/package CI, and record source-bound evidence. Update phase status and customer instructions precisely; physical/broker/Discord acceptance stays deferred.

## Verification boundaries

Use temporary stores, synthetic credentials and injected/mock HTTP. Never place broker orders or send real Discord messages for automated acceptance. Native compilation uses available local tooling and existing CI. Signed iPhone installation, actual OAuth registrations, Webull approval and physical network tests remain separate external gates. If existing platform architecture makes a requirement substantially larger, implement a complete bounded journey and record the remaining gap instead of presenting saved preferences as implemented capability.

## Review and local verification

Windows implementation `4bd7810` passed **594 Python tests**, with unraisable exceptions treated as errors. Its independent review led to lifecycle-locked configuration/test operations, guards against editing disconnected profiles and session-only publishing authorization. Tests cover stale status/preview/test completions, changed destinations/formats, uncertain acknowledgements, threaded test cancellation and explicit delivery permission. Tests remain optional and order pricing/reconciliation is unchanged.

Android implementation `40d86e6` passed complete production/test Kotlin compilation and **68 offline JUnit tests** against SDK 35, independently repeated from the final source. Its independent review led to atomic readiness/dispatch generation checks, process-owned state/IO across Activity recreation and explicit nonsticky execution-service startup. The Alerts reader has no mutation interface and uses a separate encrypted JSON store for incremental fills and destination-bound outbox history. Alerts is foreground polling, approximately every ten seconds. Changing navigation does not stop separately authorized existing Trade/Follow workers; stop them explicitly when desired.

iOS implementation `d1eb60d` adds **11 guided XCTest cases** to native CI. Independent review led to canonical Discord configuration snapshots, stale-generation guards around intent reconciliation, foreground recovery after busy operations, isolated pairing/delivery injection and a Home/setup route retaining at most five tabs. Alerts never activates intent or legacy mirroring workers; existing shared-credential identity pins remain enforced. Swift execution is not available on this Windows workstation; compilation, simulator tests and unsigned hardware archive validation run in macOS CI.

## Completed automated acceptance

- [Windows CI 40149473582](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40149473582), source `4bd7810`: 593 tests passed/one platform skip, portable and unsigned installer builds, install/upgrade/downgrade rejection/uninstall and synthetic journal/DPAPI preservation. Upgrade acceptance uses the same program payload under an acceptance-only next patch version, not a future application migration.
- [Android CI 40150273615](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40150273615), final source `032e2af`: 68 tests passed and debug APK packaged. This final revision normalizes mixed-encoding setup labels to UTF-8; full local Kotlin compilation and 68 tests were repeated after normalization. Earlier functional-source CI `40149552445` also passed on `40d86e6`.
- [iOS build CI 40149688984](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40149688984), source `d1eb60d`: simulator build and unsigned arm64 hardware archive passed validation. The archive is not an installable signed package.
- [Native/backend CI 40149692050](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40149692050), source `d1eb60d`: **94 iOS tests passed**, including the 11 guided cases; Linux passed 574 Python tests/20 platform skips. Local Windows passed all 594 Python tests.

The [source-bound report](../../acceptance/2026-10-24/guided-setup/source-evidence.json) links each exact implementation revision and downloaded artifact report. Phase F is complete for automated implementation. Physical lifecycle/UI, real broker/Discord, OAuth registration/approval and signed iPhone installation are not passed by this evidence. Android Alerts remains foreground polling; native runtime limitations remain visible in setup. Phases G–I and original external release gates remain open.
