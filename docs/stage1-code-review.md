# Stage 1 implementation code review — 2026-10-14

Scope: iOS ReplayKit lifecycle, Webull OCR recognition, observation queue, HTTPS upload, backend quarantine, and synthetic delivery tests. This is a **source review**, not a successful simulator build or an executed test report.

## Changes made during review

1. Updated screen-observation tests for dedicated upload authorization. Older tests expected an administrative credential or unauthenticated upload, inconsistent with the hardened API.
2. Replaced time-based three-second OCR deduplication. A single confirmation left on screen could previously generate a new evidence ID every three seconds. Now a continuous confirmation is coalesced until the recognized screen disappears or changes; later identical executions remain possible.
3. Added explicit ReplayKit pause, resume and finish handling; resuming resets capture throttling and retries queued evidence.
4. Prevented local evidence creation before upload configuration exists, and made disabling screen upload erase the queued JSON evidence.
5. Required timezone-aware observation timestamps on the backend.
6. Updated the root README and iOS build guide to reflect the actual implementation and its limits.

## Safety invariant

**OCR is not verified brokerage execution.** `POST /api/screen-observations` persists evidence as `pending_review` and cannot enqueue Discord jobs. The independently verified fill intake remains separate. No code in the iOS extension places trades.

## Findings still open

| Severity | Finding | Next verification |
| --- | --- | --- |
| **Blocking** | No confirmed passing Xcode/iOS Simulator build or XCTest run. | Inspect and fix macOS GitHub Actions results; verify signing and generated Xcode schemes. |
| **Blocking** | App Group and shared Keychain entitlements have not been validated on a signed physical iPhone. | Test credential save/load across app and extension with the actual Apple development team. |
| **Blocking for automatic alerts** | Webull screen OCR cannot independently prove a broker fill or distinguish all separate identical executions. | Validate supported broker-reported fill source, or add explicit operator confirmation before Discord publication. |
| High | ReplayKit capture is user-started and not a reliable always-on background monitor. | Real-device lifecycle tests, including interruptions and Webull app switching. |
| High | Retry queue is best-effort; upload does not continue after the extension stops. | Network-offline, recovery, and extension termination tests. |
| High | OCR parser currently assumes a specific textual contract layout and visible Webull identity. | Test redacted genuine Webull iOS fill, partial, canceled and preview examples. |
| Medium | Queue pruning to 100 records may discard old observations during prolonged outages. | Add explicit overflow reporting and assess retention policy. |
| Medium | Concurrent queue flush and configuration revocation can race. | Exercise revocation during in-flight network upload; server-side credential revocation is also required. |
| Medium | The iOS status interface does not yet expose pending queue depth, upload errors or server-side review status. | Add status telemetry in stage 2. |

## Verification performed

- Read and reviewed repository source through the GitHub connector.
- Added/updated source files and tests directly on `main`.
- Attempted a local repository clone for Python test execution, but this environment could not resolve `github.com`. **No test-pass claim is made.**
- A macOS/Xcode environment is not available in this runtime. CI workflow presence alone does not establish passing tests.

## Stage 1 exit assessment

**Stage 1 implementation code is substantially in place, but the milestone is not independently verified or customer-ready.** Core OCR-to-quarantined-evidence functionality is wired in code. Fully automatic, unattended Webull-to-Discord publication remains gated on independently verified execution evidence. The unresolved verification and broker-source constraints are tracked explicitly rather than bypassed.
