# Atomic Authorization Flow Implementation Plan

> **For agentic workers:** Use subagent-driven-development for isolated implementation and review. Keep the owner's direct-main/no-PR workflow.

**Goal:** Bind one-use browser authorization to a durable token reservation, with atomic revocation and no live broker access.

**Architecture:** Add candidate SQL composition functions and a private association table after the session/token stores. Keep deployment migrations and the deployed relay unchanged. All compound functions lock session owner before token scope and enforce READ COMMITTED.

**Tech Stack:** PostgreSQL 17, PGlite, SQL/dblink regression tests, existing GitHub Actions.

## Tasks

- [x] Create `supabase/tests/webull_authorization.sql` with failing assertions for `crier_webull_authorization_begin`, `consume`, and `revoke`. Test exact binding, one-use callback, supersession, failed-CAS preservation, duplicate-state rollback, environment isolation, expiry and service-only privileges. Run `npm test --prefix supabase/tests`; observe missing-function failure.
- [x] Create `supabase/webull-connect/authorization_flow.sql`: private state-digest association with FK cascade; begin returns generation, operation ID and deadline; consume returns a matching current reservation once; revoke clears browser sessions and token custody together. Reuse validators and existing RPCs under fixed-order locks. Make DDL/grants atomic and errors generic.
- [x] Explicitly load this candidate after `token_store.sql` in `supabase/tests/run-sql-tests.mjs` and `.github/workflows/supabase-tests.yml`. It must stay outside migrations.
- [x] Create `supabase/tests/integration/webull_authorization_concurrency.sql`. Hold one transaction while a second worker attempts consumption/revocation; prove no stale result can reactivate custody. Test competing initial authorization reservations and expiry during lock wait. Add it to the real PostgreSQL CI step.
- [x] Review grants, lock order, callback failures and transaction rollback. Run all local SQL suites, all Webull and gateway Deno tests, type checks, lint and `git diff --check`. Commit directly to main with `[skip ci]`, push and dispatch `supabase-tests.yml`; inspect every job result.
- [x] Record CI/source evidence and mark Phase A complete in `docs/autonomous-completion-plan.md`; update `docs/webull-connect.md` and link the new queue from the original roadmap. Keep deployment and broker claims precise.

Representative test contract (fixture digests are synthetic):

```sql
SELECT generation,operation_id,expires_at
FROM public.crier_webull_authorization_begin(
  'fixture-owner','sandbox',0,'00000000-0000-4000-8000-000000000001',
  repeat('a',64),repeat('b',64),'https://example.test/callback');
-- generation=1, exact operation ID, five-minute expiry
SELECT generation,operation_id
FROM public.crier_webull_authorization_consume(
  'fixture-owner','sandbox',repeat('a',64),repeat('b',64),'https://example.test/callback');
-- exactly one row on first use, zero rows on replay
SELECT public.crier_webull_authorization_revoke('fixture-owner','sandbox');
-- generation=2; any result for generation=1 fails token_commit
```

Outcome: source d246a7b passed CI 40118251456, including the real PostgreSQL concurrency scenarios. Five local SQL suites and 32 Deno tests, type checks and lint passed; independent review found no actionable issues. No deployment or broker requests occurred.
