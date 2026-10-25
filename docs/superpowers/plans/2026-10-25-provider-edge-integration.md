# G.6 — Supabase and customer integration

> Execute with independent platform tasks and review, directly on main as already authorized.

**Goal:** Move the verified provider protocol toward the approved Supabase Free hosting target and customer app integration. Preserve the existing transport relay and Phase F API-key recovery.

## G.6a Edge-compatible service

- [x] Implement service-only Postgres flow RPCs in a candidate schema, with row locks, owner/browser binding, active-flow quotas, expiry and one-use encrypted handoff. Add SQL permissions/concurrency regressions; do not deploy candidate SQL.
- [x] Implement WebCrypto AES-GCM custody and pinned Alpaca/Discord exchange adapters matching the Python reference. Share the return URI and preserve uncertainty after ambiguous exchange.
- [x] Implement Supabase Auth verification and a minimal browser login/BFF: distinct native JSON login and browser cookie login, same-owner checks, CSRF protection, bounded input/output, no credentials in URLs/logs and no auto-execution.
- [x] Compose a separate guarded `crier-oauth` Edge Function, pinned function base/callbacks and server-only env configuration; adapt durable RPC transport without changing `crier` relay behavior.
- [x] Review, run Deno/SQL/Postgres CI and synthetic integration tests, and record source-bound evidence and deployment prerequisites.

## G.6b Client integration

- [x] Add customer auth/session and provider-flow clients using secure device storage, installed return handling, proof-bound redemption and deliberate credential installation on Windows, iOS and Android.
- [x] Support provider Bearer credentials in the selected broker adapters while retaining API-key mode and account/environment/order-journal pins. Preserve Discord destination/outbox ownership and explicit publishing permission.
- [x] Validate end-to-end mocked login → consent return → redeemed identity → secure install → reconnect/recovery. Actual provider app registration, external login delivery, live deployment, signing and physical acceptance remain separate requirements.

Use synthetic accounts and injected network ports throughout automated tests. Browser login identifies the same Crier/Supabase customer as the native session; it never requests brokerage passwords. The service must fail closed without complete external-key/provider configuration. No real provider grant, message, trade, schema deployment or service secret is required for source verification.

## Implementation and review disposition

Edge source `d2b02c6` and native source `cecaefb` implement the scoped source work. Review fixes fence cancellation during in-flight redemption, publish Windows return files atomically, quarantine destinations belonging to another customer/project, preserve destination provenance during ordinary settings saves, block queued Android starts during logout, and invalidate old iOS mutation clients without preventing a fresh foreground reconciliation client. Offline journals and uncertain-delivery evidence survive these boundaries.

The Edge/PostgreSQL workflow, relay regressions, Python platform matrix, Windows packaging/installer acceptance, Android compilation/tests and iOS simulator/unsigned archive passed. After fixture/storage isolation correction `2159e3b`, all **107 iOS behavioral tests passed**. Final source-bound evidence is recorded in the [integration report](../../acceptance/2026-10-25/provider-integration/source-evidence.json). Implementation checkmarks do not claim live activation.

Remaining external gates are registered provider applications/callbacks, protected configuration and deployment of the new service, real consent interoperability, distribution/signing and physical acceptance. Webull approval and its adapter are separate from Alpaca/Discord integration. The transport relay was not deployed or changed by these commits.
