# Phase 6 pending cloud authorization sessions

**Goal:** Prepare durable single-use OAuth state for the hosted runtime, preserving the isolation properties of the local Python session primitive.

**Architecture:** A private PostgreSQL schema stores only SHA-256 digests, an opaque owner reference, pinned environment/callback and a five-minute lifetime. Service-role-only RPCs create, consume and revoke pending sessions. The candidate SQL stays outside `supabase/migrations/` and is explicitly loaded only by test runners; no deployment occurs. A pure Deno helper generates fresh state/browser-binding values with Web Crypto and hashes the UTF-8 values consistently with Python.

## Tasks

- [x] Test-first candidate SQL: least-privilege schema/RPC grants, fixed lifetime, bounded owner sessions, exact identity/binding checks and atomic single-use consumption.
- [x] Generate opaque server-side state material with CSPRNG values, hash-only persistence fields and redacted ordinary serialization.
- [x] Add local and real PostgreSQL tests, including simultaneous redemption, expiry while waiting for a lock, owner quotas and revocation.
- [x] Independently review and run existing relay/contract checks. Run targeted CI, retain results and update integration status.

Outcome: three local SQL suites, 23 Deno tests and type/lint checks passed. Real PostgreSQL/security/concurrency verification passed in [CI 40093696777](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40093696777), source `4bfcc3f`. The review's stale-snapshot revoke issue and the environment-name mismatch received regression coverage and were corrected before CI. Candidate DDL/grants apply atomically. No deployment or broker request occurred; the repository still uses only `main`.

## Security boundaries

The future authenticated gateway must derive the owner reference from its verified customer session and pin the callback from protected configuration. Database RPC credentials are server-only; these functions do not authenticate a customer by themselves. No broker access/refresh token, partner application secret, HTTP endpoint or browser cookie handler is implemented here. Keep the pending SQL out of deployment migrations until the complete gateway, permissions, token custody and approved Webull sandbox behavior are validated.
