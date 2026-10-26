# Phase L push delivery and observational dashboard implementation plan

> **For agentic workers:** Use subagent-driven-development or executing-plans task-by-task; respect the ownership contract and standing direct-main/no-PR authorization.

**Goal:** Push durable order instructions and observational execution updates across iOS/Android/Windows, with a read-only consolidated dashboard.

**Architecture:** Authenticated SSE clients, private Supabase Realtime wake bridge / local committed notifications, durable cursor catch-up and explicit polling fallback. Separate bounded telemetry outbox and role-filtered snapshots; dashboard data never authorizes trading.

**Tech stack:** Existing Python/httpx/FastAPI/Tk, Swift/URLSession/SwiftUI, Kotlin/HttpURLConnection/native UI, Deno Web Streams, PostgreSQL and private Supabase Broadcast.

- [ ] L.1 Shared strict status/presence/dashboard models, reference monetary/unknown fixtures, Python relay persistence/privacy and committed notifications. Tests first, then implementation and focused verification.
- [ ] L.2 Supabase migration/RPC/private notifications, authenticated bounded SSE and Realtime bridge. SQL/Deno red-green tests for isolation, replay, races and cleanup.
- [ ] L.3 Python streaming/fallback receiver, independent telemetry and Windows read-only dashboard; tests for cursor/lifecycle/health/no-trade effects.
- [ ] L.4 Android streaming/fallback, execution/outbox wake signals, observational publisher/dashboard and shared fixtures; compile/unit/UI regressions.
- [ ] L.5 iOS streaming/fallback, pending-process wake, observational publisher/dashboard and shared fixtures; native lifecycle/decoder/money tests.
- [ ] L.6 Cross-platform review, offline push/fill stress/recovery/accuracy, full/native/platform/package CI and source-bound evidence. Deploy/probe isolated hosted synthetic channels if existing access permits; no real orders or Discord posts. Update setup/latency/remaining-work docs and push main.

Frozen contract: [push and dashboard](../specs/2026-10-26-push-dashboard.md). The user's prior dashboard and push-flow approval covers implementation; no new approval interview or per-trade confirmation is introduced.
