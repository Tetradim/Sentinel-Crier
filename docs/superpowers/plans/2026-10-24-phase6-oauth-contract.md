# Phase 6 Webull Connect OAuth contract

**Goal:** Implement the documented OAuth request/response boundary while approved Webull access remains unavailable.

**Architecture:** Add a pure TypeScript module beside Supabase tooling, outside deployable `functions/`. It prepares authorization parameters and token-grant forms for pinned sandbox/production endpoints, validates token replies and expiry/identity, and redacts ordinary object serialization. It performs no requests, stores no tokens and exposes no endpoint. Existing Python one-use session storage remains separate groundwork; customer authentication, hosted state storage and a token vault are still required.

**Source:** Official rendered [authorization-code reference](https://developer.webull.com/apis/docs/reference/connect-api/get-authorization-code/) and [token reference](https://developer.webull.com/apis/docs/reference/connect-api/create-and-refresh-token/), read October 24, 2026. Rendering exposed request/response schemas omitted by the static page text used in the earlier review. The [Connect guide](https://developer.webull.com/apis/docs/connect-api/about-connect-api/) supplies environment distinctions; an approved partner integration must confirm its entry point and permissions.

## Tasks

- [x] Read rendered request/response contracts without sending an API request or submitting another application.
- [x] Test-first implementation in `supabase/webull-connect/oauth_contract.ts` and `_test.ts`: form encoding, grant separation, identity/expiry checks, environment isolation and secret-redacted errors/serialization.
- [x] Add offline contract tests, type checking and lint to existing Supabase CI. Keep both the existing relay and its deployment configuration unchanged.
- [x] Independently review the boundary and run offline Deno checks plus existing relay/SQL checks appropriate to the CI change.
- [x] Record verified scope, unresolved signing/vault/browser details and approval-dependent sandbox checks. Commit/push directly to main.

Evidence: local nine-group contract tests, ten existing gateway tests, type/lint checks and local SQL checks passed. Real PostgreSQL and complete targeted checks passed in CI `40090804881`, source `3c5ec69`. Independent review's three validation findings received regression tests and were fixed/rechecked. No hosted deployment or real broker call occurred.

## Exit boundaries

Passing this plan completes contract groundwork only. No HTTP request signer, token exchange route, hosted credential vault, customer login, native Webull connection or trading adapter is enabled. Sandbox account tests, token refresh races, broker-app event timing and real orders require approved access and remain unverified. Partner secrets must stay on a protected server and must not enter the native binaries.
