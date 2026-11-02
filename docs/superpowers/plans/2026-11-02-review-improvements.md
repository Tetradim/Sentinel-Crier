# Review improvements implementation plan

> Agentic workers: use subagent-driven-development for scoped implementation and independent review. User authorized execution on main; do not create a PR.

**Goal:** Extend native conformance coverage, reduce journey-controller density, expose selected diagnostic failures safely, and present recent decisions in plain language.

**Architecture:** Keep the native engines and durable state formats. Extend shared fixtures with real Python/Kotlin/Swift consumers. Extract presentation/journey coordination while preserving public DesktopApp callbacks and Android process/lifecycle owners. Diagnostic recording remains bounded, sanitized and nonfatal. The decision presentation reads existing evidence and never authorizes execution.

**Tech stack:** Python/Tk, Kotlin Android Views, Swift/XCTest, shared JSON and existing CI.

## 1. Shared native scenarios

- [x] Add versioned clock and ownership/reconciliation scenarios under tests/fixtures and dedicated native consumers. Exercise production APIs; assert expected values/refusals, including drift boundary, negative monotonic progression, reservations/identity and cumulative-fill corrections as APIs permit.
- [x] Wire the same resource into ios/project.yml and Android's existing shared-resource directory. Document exact coverage and intentional lifecycle/storage differences in docs/protocol/native-invariants.md.
- [x] Run focused Python and available Android checks before starting coordinator changes. Hosted iOS verification follows integration.

## 2. Journey coordinators

- [x] Characterize existing disconnected/connected journey selection and stop/reconnect behavior with tests.
- [x] Extract desktop journey/navigation coordination into crier/desktop_journeys.py while preserving DesktopApp callbacks and existing action epoch/route guards. Keep views and broker worker boundaries intact.
- [x] Extract Android journey persistence/selection into JourneyCoordinator.kt with callbacks for stop, purpose, navigation and rebuild. Keep process-owned writers/OAuth inbox and lifecycle checks in their original owners. Run tests proving transition ordering and no implicit connect/enable.

## 3. Selective diagnostics

- [x] Add tests showing diagnostic transport/clock failures emit fixed error codes without exception messages, credentials or raw payloads; logger failure must not alter retry/stop semantics.
- [x] Use the existing error_log sink for selected DiagnosticsClient failures and dropped IntentDevice trace/queue evidence. Leave expected wait timeouts quiet and avoid recursive logging from error_log itself.
- [x] Verify retry limits, journal behavior and broken-sink resilience with targeted tests.

## 4. What happened presentation

- [x] Add a bounded plain-language projection of existing execution/trace evidence, with truthful pending/unknown/partial/paused states, no inferred successful fills, and no raw payload formatting.
- [x] Add a read-only Windows panel reachable from Home/Account and use selected local trade evidence. Preserve advanced timeline/export access. Include clear empty/unavailable states and clear evidence on route change.
- [x] Document its observational scope and add UI tests for selection, stale callback/route isolation and disabled execution. Keep native fixture coverage on Android/iOS; extend decision presentation to native mobile where their existing evidence screens support equivalent semantics without new broker access.

## Verification and delivery

- [ ] Run full Python/Tk tests and platform CI, independently review spec compliance and correctness, fix reproduced issues, and capture the changed UI using an isolated profile.
- [ ] Commit/push verified code directly to main. Record exact checks and any owner-deferred physical/provider acceptance separately; no real broker orders or Discord messages.
