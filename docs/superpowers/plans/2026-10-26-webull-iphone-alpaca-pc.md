# Webull iPhone to Alpaca PC implementation plan

**Goal:** Implement the approved in-Crier Webull-host path using the existing paper receiver protocol.

**Architecture:** Isolate Webull credentials/trading behind a customer-authenticated server boundary. Add an independent native Webull host journal and screen, retaining existing intent-v1 and the Windows Alpaca executor. Keep provider acceptance separate from synthetic verification.

**Tech stack:** Swift/SwiftUI, TypeScript/Deno, existing PostgreSQL/Supabase authorization primitives, Python receiver regression tests.

- [x] Trace current broker, authorization, relay and native entry boundaries; record approved scope.
- [x] Write server behavioral tests for principal/account binding, canonical instruments, one-time submissions, partial/unknown status and cancellation.
- [x] Implement the gateway, signed Connect transport, service-role RPC ledger and explicit unavailable state. The concrete approved resource/token-custody Provider remains unfinished below.
- [x] Write native host tests for durable publication, separate source/destination environments, rejection/cancellation and restart behavior.
- [x] Implement the candidate Webull host screen, service authorization interface, paper-receiver pairing and durable order lifecycle.
- [x] Verify canonical Webull-host instructions execute through the existing Windows/Python Alpaca-paper path without source credentials using intercepted HTTP.
- [x] Review changed execution boundaries; run affected suites and iOS CI where available.
- [x] Update configuration/status docs, record exact automated results and unresolved provider/device dependencies; commit/push main.

No real order placement, provider enrollment or activation is performed by synthetic tests. New strategies and general multiple-host routing remain outside this slice.

## Outstanding integration work

- Webull approval and issued account/resource/permission details.
- Concrete Provider composition: authorization coordinator and callback/cookie flow, encrypted token custody/refresh, approved resource schemas, exact contract discovery and long-only stock/option submission semantics. This is further implementation, not merely supplying credentials to the candidate.
- Protected service configuration, per-customer request limits, operator deployment and native default gateway configuration after activation.
- Real Webull sandbox → Alpaca-paper cross-network acceptance, Apple signing and physical iPhone/Windows behavior.

Review corrected a permanent cancellation latch and competing view-instance journal writers. Additional regressions reject contradictory receipt identity/fills and prevent failed fresh broker lookups from returning cached terminal evidence as success. The production native view now uses one shared journal owner. Source fill averages are retained separately from limit prices.

[Candidate verification](../../acceptance/2026-10-26/webull-iphone-host/README.md): 1,036 Python tests/one optional SDK skip, 22 Deno tests, five PGlite SQL tests, 172 iOS native tests, simulator build and unsigned hardware archive. Exact source revisions and matching runtime components are recorded. The approved Provider and deployment above remain unfinished; the candidate is not a completed live Webull product.
