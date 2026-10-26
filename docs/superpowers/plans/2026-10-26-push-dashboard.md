# Phase L push delivery and observational dashboard implementation plan

> **For agentic workers:** Use subagent-driven-development or executing-plans task-by-task; respect the ownership contract and standing direct-main/no-PR authorization.

**Goal:** Push durable order instructions and observational execution updates across iOS/Android/Windows, with a read-only consolidated dashboard.

**Architecture:** Authenticated SSE clients, private Supabase Realtime wake bridge / local committed notifications, durable cursor catch-up and explicit polling fallback. Separate bounded telemetry outbox and role-filtered snapshots; dashboard data never authorizes trading.

**Tech stack:** Existing Python/httpx/FastAPI/Tk, Swift/URLSession/SwiftUI, Kotlin/HttpURLConnection/native UI, Deno Web Streams, PostgreSQL and private Supabase Broadcast.

- [x] L.1 Shared strict status/presence/dashboard models, reference monetary/unknown fixtures, Python relay persistence/privacy and committed notifications. Tests first, then implementation and focused verification.
- [x] L.2 Supabase migration/RPC/private notifications, authenticated bounded SSE and Realtime bridge. SQL/Deno red-green tests for isolation, replay, races and cleanup.
- [x] L.3 Python streaming/fallback receiver, independent telemetry and Windows read-only dashboard; tests for cursor/lifecycle/health/no-trade effects.
- [x] L.4 Android streaming/fallback, execution/outbox wake signals, observational publisher/dashboard and shared fixtures; compile/unit/UI regressions.
- [x] L.5 iOS streaming/fallback, pending-process wake, observational publisher/dashboard and shared fixtures; native lifecycle/decoder/money tests.
- [x] L.6 Cross-platform review, offline push/fill stress/recovery/accuracy, full/native/platform/package CI and source-bound evidence. Deploy/probe isolated hosted synthetic channels if existing access permits; no real orders or Discord posts. Update setup/latency/remaining-work docs and push main.

Frozen contract: [push and dashboard](../specs/2026-10-26-push-dashboard.md). The user's prior dashboard and push-flow approval covers implementation; no new approval interview or per-trade confirmation is introduced.

## Completed verification

Accepted source `a7ee75c` passed 1,024 full local Python tests (one optional SDK skip), 162 Android unit tests, 157 iOS native tests, five Android emulator tests and one iOS simulator UI test. PostgreSQL/Deno, Windows portable and installer lifecycle, native compilation and unsigned iPhone archive checks passed. Eight successful source-bound CI runs and exact component reuse are recorded in the [acceptance report](../../acceptance/2026-10-26/push-dashboard/source-evidence.json).

The testing Supabase migration and Crier function are deployed. An isolated synthetic paper channel verified streaming, durable cursor identity, device-report arithmetic and revocation. No broker orders or Discord messages were sent. Manual integration review corrected report/reconnect/cache races; independent agent review was unavailable because the selected model reported capacity. Apple/Webull/provider activation, real broker-UI reconciliation, physical and customer cross-network acceptance remain deferred.
