# Webull Connect integration status

October 24, 2026: Phase 6 work has started after completing available Phase 5 acceptance work. The owner's last approval-status update remains "still waiting." Do not submit another application. Webull login and trading are not available in released Crier clients.

## Implemented groundwork

`crier/webull_connect_sessions.py` is an isolated server-side authorization-session primitive. It creates independent random state and browser-binding secrets, stores only their SHA-256 hashes, and binds redemption to an authenticated customer identity, sandbox/production environment and configured HTTPS callback. Sessions expire after five minutes; matching redemption deletes the session in one transaction. Invalid attempts leave the legitimate session intact. Concurrent callbacks cannot both succeed. A gateway must use a new session after any failed or uncertain code exchange.

This module is not connected to the apps, HTTP endpoints, Webull or the deployed Supabase relay. It holds no broker tokens. Its SQLite persistence supports restart and local concurrency testing; it is not a storage option for ephemeral Supabase Edge Functions. The candidate PostgreSQL equivalent below is prepared for testing but has not been deployed or integrated into a gateway.

The future gateway must authenticate the customer when starting authorization, bind the second secret to a Secure/HttpOnly browser cookie, enforce request limits, check the exact registered redirect and verify the callback before exchanging its code. The user identity must come from the authenticated session, never a callback query parameter. Cookie policy and browser return behavior must be tested on all platforms. State alone is not customer authentication.

## Documentation findings

Webull's [OAuth integration guide](https://developer.webull.com/apis/docs/connect-api/authentication/) requires server-held application secrets. Codes are single-use and short-lived; refresh rotates both tokens. Use the returned expiry values, not hard-coded token lifetimes. The five-minute Crier login session does not extend Webull's authorization-code validity.

The [Connect overview](https://developer.webull.com/apis/docs/connect-api/about-connect-api/) separates sandbox and production services and requires following Connect-specific resource paths and headers. The existing `crier/webull.py` SDK observer implements the separate Trading API flow; its credentials and payload assumptions cannot establish Connect compatibility.

The static text initially available from the public [authorization-code](https://developer.webull.com/apis/docs/reference/connect-api/get-authorization-code/) and [token](https://developer.webull.com/apis/docs/reference/connect-api/create-and-refresh-token/) pages did not expose their schemas. On October 24, reading the rendered reference exposed the required fields. The new offline contract module uses those documented fields; no request signer or network dispatcher has been implemented.

## Offline hosted-runtime contract

`supabase/webull-connect/oauth_contract.ts` targets the future server runtime but lives outside deployable Edge Functions. It contains no HTTP, environment-secret reads or persistence. No Webull endpoint has been deployed, and the existing relay remains unchanged.

The module prepares required browser authorization parameters without choosing the approved browser entry point. Token requests pin the environment's API host and `/oauth2/tokens/create`, encode form data and keep authorization-code and refresh grants separate. The reply decoder validates the documented Bearer token fields, timezone-aware issuance, positive integer-string lifetime values and optional previously bound identity. Deadlines use broker issuance time rather than extending validity from response receipt.

Callback structure is restricted to a server HTTPS URI without credentials, query, fragment, raw whitespace or backslashes; a future gateway must additionally pin the exact registered URI from protected configuration. Unknown decoder-option keys are rejected so a misspelled identity-binding option cannot silently disable that check. Future issuance is limited to 30 seconds of clock skew as a **Crier validation policy**, not a Webull service guarantee; sandbox validation must verify operational clock assumptions before use.

Opaque request/token objects redact default JSON/string/inspection output; explicit form/token accessors expose their sensitive values for future server use. That does not protect raw HTTP bodies or explicitly serialized forms if a future caller logs them. Native clients must never import application secrets or receive these server-side objects.

The Python session primitive, TypeScript contract and pending PostgreSQL store are separate building blocks, not an integrated login flow. An authenticated customer boundary, hosted integration/deployment, encrypted broker-token custody, refresh locking/rotation, token revocation and approved callback/browser behavior still need implementation and validation before real credentials are accepted.

## Candidate PostgreSQL session persistence

`supabase/webull-connect/session_store.sql` is intentionally **outside deployment migrations**. Test runners explicitly load it into isolated databases. It creates a separate private authorization-session schema and service-role-only create/consume/revoke RPCs; application roles cannot read or write its tables directly. The deployed relay and migration directory are unchanged.

Each pending session binds an opaque authenticated-owner reference, independent state/browser SHA-256 digests, `sandbox` or `production`, an exact configured callback and a 300-second lifetime. Creates are capped at five pending sessions per owner across both environments. Create/revoke use owner transaction locks and reject isolation levels other than READ COMMITTED, avoiding stale snapshots that could miss committed sessions. Consume locks its matching row before checking wall-clock expiry; invalid bindings do not consume a legitimate session. Revoke affects pending sessions for the exact owner/environment and does not undo an already completed callback/token exchange.

`session_material.ts` generates independent 32-byte Web Crypto random values, encodes them as URL-safe state/browser material and exposes only their SHA-256 persistence fields by default. Hashing uses the UTF-8 token text, matching the Python primitive. Ordinary serialization/inspection redacts raw values; explicit accessors are reserved for the future authorization redirect and server-only cookie handler. Start every new authorization with fresh material, including after consumption or revocation.

SQL cannot establish customer authentication or prove nonce entropy. A future trusted gateway must derive the owner from its authenticated session, validate/pin the registered callback using the stricter contract helper, keep service-role access server-side and enforce request limits. Pending state is not a broker token vault; no access/refresh tokens or partner secrets are stored by this schema. Atomic candidate installation keeps default function privileges from becoming visible before their revocation.

Local verification passed all three SQL suites and 23 Deno tests (10 existing gateway, 9 OAuth contract, 4 state-material tests), type checks and lint. Independent review caught and corrected a stale-snapshot revocation case; environment parity and its regressions were also corrected. Real PostgreSQL concurrency results are recorded after the focused CI run.

### Signing contract requiring confirmation

The rendered Connect token reference specifies form encoding and interface `v2`. The general [signature guide](https://developer.webull.com/apis/docs/authentication/signature/) describes `v3` and JSON POST bodies. Both require signing headers, but that general example alone does not establish how the approved Connect form request must be signed. Confirm exact canonicalization, headers/version and error responses with the partner sandbox. The App Secret is signing material, not an HTTP header to forward from the reference widget.

The guide's sandbox/prod H5 browser-login paths and the reference's API authorization-code path are recorded separately. Approval must establish the correct entry/redirect behavior for Crier; parameter preparation is not evidence of a working browser session.

## Validation evidence

Local Deno 2.9.6 verification passed nine synthetic contract test groups, type checking and lint. The existing relay gateway's ten tests and the PostgreSQL-compatible local SQL tests also passed. Tests cover reserved-character form encoding, grant/environment separation, exact expiry and clock boundaries, identity binding, malformed timestamps/callbacks, unknown options and redaction. No network permissions or broker credentials are required by the contract tests. The Supabase workflow now runs them alongside the existing relay checks; this workflow does not deploy anything.

[CI 40090804881](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40090804881), source `3c5ec69`, passed the contract test/type/lint checks, existing gateway checks, PostgreSQL-compatible local tests and real PostgreSQL migration/security/concurrency checks. Independent re-review confirmed all three contract findings below were closed.

Independent review initially found callback URL, decoder-option typo and future-issuance validation gaps. All three received failing regression tests before correction; the nine-group verification above includes those fixes.

## Work after approval

1. Confirm granted scopes, approved redirect URI, sandbox credentials, signing rules, request schemas and native-app permission model. Never include partner secrets in binaries or source control.
2. Build a separately isolated authenticated exchange service. Decide token custody, encryption, per-customer authorization, refresh locking, rotation, revocation, audit redaction and deletion before accepting credentials. The existing connection relay remains transport-only.
3. Add browser authorization and deep-link return flows to each client; verify state/binding rejection, account identity and environment separation against the sandbox.
4. Implement account, option-contract resolution, submit/replace/cancel, positions and order reconciliation using approved Connect contracts. Establish what events are available for orders entered through Webull's own app; do not promise submission-time observation before that is proven.
5. Apply the existing intent lifecycle tests and broker UI reconciliation acceptance to Webull. Test token expiry/refresh races and reconnect backfill. Keep execution disabled until those pass; mocks alone do not establish brokerage support.
