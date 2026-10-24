# Autonomous Phases B–D execution plan

**Goal:** Finish the coordinator, recovery controls and synthetic integration evidence in the approved autonomous queue.

**Architecture:** Server-only injected authentication/signing ports connect the existing contract/vault to a strict RPC adapter. Candidate SQL adds exact-envelope key-rotation CAS and bounded expiry cleanup. Node 24/PGlite executes the actual libraries together; real PostgreSQL CI supplies concurrency evidence. No public gateway or live deployment is included.

## B — Coordinator

- [x] Write failing tests for `coordinator.ts` before implementation; verify every public method derives ownership through the verifier.
- [x] Pin environment/callback/browser entry and require approval/signing readiness; reject unknown/unsafe configuration.
- [x] Consume one-use authorization before dispatch, enforce bounded timeout, encrypt replies and commit the reserved operation.
- [x] Claim rotating refresh once, enforce expected identity, mark uncertainty and prohibit blind retries.
- [x] Test `rpc_store.ts` argument mapping, role-scoped compound procedures, cardinality, safe integers, timestamps, ciphertext structure and generic errors.

## C — Operations

- [x] Add test-first `operations.sql` rotation CAS with unchanged identity/lifetimes and generation, plus bounded ordered expiry cleanup with SKIP LOCKED.
- [x] Add service-only grants, fixed search paths, metadata/expiry regressions and real PostgreSQL rotation/refresh/revoke/cleanup races.
- [x] Add authenticated `operations.ts` rotation/status and separately operator-verified cleanup. Supply fixed secret-free audit events; contain synchronous/asynchronous audit failures.
- [x] Document configuration, key rotation, uncertainty recovery, cleanup and the undeployed boundary in `docs/webull-server-operations.md`.

## D — Acceptance and evidence

- [x] Observe missing-module failure before implementing `offline-acceptance.mjs`; exercise coordinator, strict adapter, real SQL and encryption together in nine synthetic scenarios.
- [x] Add machine-readable capability reporting, dirty-source attribution and bounded scenario waits; retain CI report artifact.
- [ ] Run all relevant local suites and targeted real PostgreSQL CI; inspect full results and retain source-bound evidence.
- [ ] Update the autonomous queue and integration status; commit/push directly to main without PRs. Preserve original external/physical release gates separately.

Native application and trading runtime sources are unchanged by this slice. Their earlier acceptance evidence remains tied to its original source commits; no new physical or signed-build claim is made.
