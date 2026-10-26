# Webull iPhone to Alpaca PC implementation plan

**Goal:** Implement the approved in-Crier Webull-host path using the existing paper receiver protocol.

**Architecture:** Isolate Webull credentials/trading behind a customer-authenticated server boundary. Add an independent native Webull host journal and screen, retaining existing intent-v1 and the Windows Alpaca executor. Keep provider acceptance separate from synthetic verification.

**Tech stack:** Swift/SwiftUI, TypeScript/Deno, existing PostgreSQL/Supabase authorization primitives, Python receiver regression tests.

- [x] Trace current broker, authorization, relay and native entry boundaries; record approved scope.
- [ ] Write server behavioral tests for principal/account binding, contract mapping, one-time submissions, partial/unknown status and cancellation.
- [ ] Implement gateway/adapter with official transport requirements and explicit unavailable state until configured/approved.
- [ ] Write native host tests for durable publication, separate source/destination environments, rejection/cancellation and restart behavior.
- [ ] Implement Webull host screen, service authorization, paper-receiver pairing and durable order lifecycle.
- [ ] Verify canonical Webull-host instructions execute through the existing Windows/Python Alpaca-paper path without source credentials.
- [ ] Review changed execution boundaries; run affected suites and iOS CI where available.
- [ ] Update configuration/status docs, record exact automated results and unresolved provider/device dependencies; commit/push main.

No real order placement, provider enrollment or activation is performed by synthetic tests. New strategies and general multiple-host routing remain outside this slice.
