# Remaining implementation without owner input

October 24, 2026. Baseline: main `8f267e7`. This is the implementation queue for work that can be completed with source access, synthetic fixtures and existing CI. It supplements the original roadmap; completing it does not change that roadmap's release acceptance requirements.

At this plan's baseline, the available implementation work in original Phases 1–5 had passed its recorded checks. Phase 6 still had separate authorization, encryption and database primitives. The completed tasks below connect them within the planned offline scope without inventing an approved broker contract or requiring credentials.

```mermaid
flowchart LR
    A[A. Atomic authorization lifecycle] --> B[B. Server coordinator]
    B --> C[C. Recovery and operational controls]
    C --> D[D. Automated acceptance and handoff]
```

| Phase | Work executable without owner input | Completion evidence |
| --- | --- | --- |
| A — Atomic authorization lifecycle | Reserve a token generation and create its browser session atomically; return the reserved operation only after exact, single-use callback validation; revoke pending browser state and token custody together. Reject stale callbacks, cross-account/environment attempts and late results. | Local SQL security regressions and real PostgreSQL concurrent begin/consume/revoke tests. |
| B — Server coordinator | Connect verified-principal inputs, pinned configuration, session material, database RPCs and vault APIs. Add bounded exchange/refresh dispatch through an injected transport; fail closed when required signing configuration is absent. Validate every reply before persistence and use one refresh claim per attempt. | Synthetic end-to-end coordinator tests for successful login/refresh, denied identities, replay, timeout, response loss, malformed replies and revoke races. No broker calls. |
| C — Recovery and operational controls | Add generation-protected key rewrapping; bounded expired-session cleanup; secret-free status/audit events; explicit reauthorization recovery after uncertainty; deployment configuration validation and operator recovery instructions. Keep tombstones needed for stale-result rejection. | Key rotation/revocation races, expiry cleanup bounds, audit redaction and invalid configuration tests; repeatable isolated recovery drill. |
| D — Automated acceptance and handoff | Run the complete available test matrix, add coordinator protocol/fault fixtures, produce a machine-readable capability/evidence report and update support/setup documentation to reflect implemented behavior precisely. | CI results tied to source commits, reproducible fixture runs and a report distinguishing implemented, integrated and actually deployed features. |

Only source and test work is scheduled here. External approvals, owner account operations, real credentials, physical trials and distribution submissions are excluded. The original roadmap retains those requirements separately. No new public endpoint, broker capability or live deployment is implied by this plan.

## Phase A design

Create a candidate `authorization_flow.sql` after the existing session and token stores. A private association binds each state digest to a token generation and operation ID. Server-only begin/consume/revoke RPCs coordinate both stores, acquire locks in the fixed order **session owner, then token scope**, and reject fixed-snapshot transactions. A new successful authorization supersedes the previous pending session in that owner/environment; a failed compare-and-set or duplicate state must leave existing state unchanged.

Begin reserves before redirect, creates the session and association in one transaction and returns the reservation plus deadline. Consume validates exact owner/environment/callback/browser digest, checks expiry after locks, verifies that the reservation is still current, then deletes the one-use session and returns the bound generation/operation. Revoke deletes pending state and increments the token tombstone in one transaction. A callback already consumed before revoke may still reach a remote broker; its stale result must fail the existing token commit fence.

The implemented coordinator uses these compound operations instead of separately calling the lower-level building blocks. All operations remain service-role-only; they do not authenticate customers. No native client receives service keys, broker tokens or application secrets.

## Execution status

- [x] A: atomic authorization lifecycle — implemented and verified.
- [x] B: server coordinator — implemented with trusted injected authentication/signing ports.
- [x] C: recovery and operational controls — rotation CAS, bounded cleanup and safe status/audit hooks.
- [x] D: automated acceptance and handoff — source-bound evidence retained.

Phase A evidence: source `d246a7b`, [CI 40118251456](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40118251456). All five local SQL suites and 32 local Deno tests passed, with type checks and lint. Real PostgreSQL 17 CI passed initial reservation races, supersession, single callback consumption, revoke versus late commit/pending callback, and expiry during a lock wait. Independent review found no actionable issues.

Phases B–D evidence: source `6788b4c`, [CI 40119328343](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40119328343). Local verification passed 542 Python tests, 55 Deno tests, six SQL suites and nine integrated coordinator/SQL/vault scenarios. CI passed PostgreSQL 17 rotation/refresh/revoke and parallel cleanup races, existing security/concurrency suites, Deno checks and the integrated scenarios. The downloaded [capability report](acceptance/2026-10-24/webull-offline-acceptance.json) records a clean source tree, synthetic integration and no deployment or broker acceptance. Review findings about evidence attribution and asynchronous audit rejection were fixed with regressions; final review found no remaining product/security issues.

The [operator guide](webull-server-operations.md) covers composition and recovery. Phases A–D are complete for their declared offline scope. The owner subsequently authorized the [customer ease-of-use phases E–I](customer-ease-plan.md); Phases E and F are complete for their automated implementation scope with native CI evidence. Phase G now has verified Alpaca/Discord exchange, custody, HTTP composition and native return-contract preparation; its customer login, deployment adapter and credential-installation integration remain open as G.6. H and I remain open. No HTTP gateway, customer authentication implementation, approved signer, native Webull flow or broker adapter is deployed by A–D. Original release gates remain separate; the full Webull product is not complete.
