# Phase 5 automated acceptance

**Goal:** Exercise the supported Alpaca release path with reproducible synthetic evidence while honoring the owner's deferral of physical acceptance and owner-dependent Phase 4 work.

**Architecture:** Keep existing relay and execution implementations. Use isolated temporary journals and mock Alpaca HTTP transports for integrated execution acceptance. Run the local relay load harness separately from a bounded synthetic test of the deployed HTTPS service. No real brokerage or Discord destination is configured by these checks.

## Execution

- [x] Record explicit Phase 4 deferrals, retaining unmet distribution requirements as deferred rather than passed.
- [x] Run local relay load/recovery at a declared synthetic load and retain its aggregate JSON.
- [x] Run the hosted synthetic PAPER transport check; revoke its test receivers afterward.
- [x] Add integrated transport/execution acceptance covering exact options, partial-fill replacement, cancel/exit ownership, duplicate delivery and ambiguous submission restart. Verify broker requests through mock HTTP, not a live account.
- [x] Retain machine-readable Python, Android and iOS automated test evidence. Add manual CI entry points where missing and upload native test results.
- [x] Run complete source checks and relevant native CI, review the new tests, and publish a [Phase 5 results/deferred matrix](../../phase5-results-2026-10-24.md).

Outcome: 521 local Python tests passed; Linux and Windows each passed 520 with one platform-specific skip. Android passed 44 tests and iOS passed 83. Local relay load delivered 900/900; the hosted bounded synthetic transport check passed and revoked its test receivers. An existing clock-dependent invalid-lifetime fixture exposed by Windows was made deterministic in `18e284a`; no production trading changes were needed. Physical and real-broker acceptance remains unverified.

## Acceptance boundaries

Local ASGI timing is not network delivery latency or a hosted capacity guarantee. The hosted transport check does not execute brokerage orders. Mock Alpaca responses cannot establish parity with a real brokerage UI. Physical cross-network mobile operation, signed-device installation, actual paper brokerage account accuracy/latency and live-market execution remain unverified/deferred. Do not silently advance to a release declaration when those gates remain open.
