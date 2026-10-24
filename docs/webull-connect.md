# Webull Connect integration status

October 24, 2026: Phase 6 work has started after completing available Phase 5 acceptance work. The owner has approved the implementation plan and explicitly confirmed that Webull's response is still pending. Do not submit another application. Webull login and trading are not available in released Crier clients.

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

The Python session primitive, TypeScript contract and candidate PostgreSQL stores are separate building blocks, not an integrated login flow. The custody primitives below prepare encryption and refresh fencing. An authenticated customer boundary, integrated exchange/refresh orchestration, hosted deployment, remote token revocation and approved callback/browser behavior still need implementation and validation before real credentials are accepted.

## Candidate PostgreSQL session persistence

`supabase/webull-connect/session_store.sql` is intentionally **outside deployment migrations**. Test runners explicitly load it into isolated databases. It creates a separate private authorization-session schema and service-role-only create/consume/revoke RPCs; application roles cannot read or write its tables directly. The deployed relay and migration directory are unchanged.

Each pending session binds an opaque authenticated-owner reference, independent state/browser SHA-256 digests, `sandbox` or `production`, an exact configured callback and a 300-second lifetime. Creates are capped at five pending sessions per owner across both environments. Create/revoke use owner transaction locks and reject isolation levels other than READ COMMITTED, avoiding stale snapshots that could miss committed sessions. Consume locks its matching row before checking wall-clock expiry; invalid bindings do not consume a legitimate session. Revoke affects pending sessions for the exact owner/environment and does not undo an already completed callback/token exchange.

`session_material.ts` generates independent 32-byte Web Crypto random values, encodes them as URL-safe state/browser material and exposes only their SHA-256 persistence fields by default. Hashing uses the UTF-8 token text, matching the Python primitive. Ordinary serialization/inspection redacts raw values; explicit accessors are reserved for the future authorization redirect and server-only cookie handler. Start every new authorization with fresh material, including after consumption or revocation.

SQL cannot establish customer authentication or prove nonce entropy. A future trusted gateway must derive the owner from its authenticated session, validate/pin the registered callback using the stricter contract helper, keep service-role access server-side and enforce request limits. Pending state is not a broker token vault; no access/refresh tokens or partner secrets are stored by this schema. Atomic candidate installation keeps default function privileges from becoming visible before their revocation.

Local verification passed all three SQL suites and 23 Deno tests (10 existing gateway, 9 OAuth contract, 4 state-material tests), type checks and lint. Independent review caught and corrected a stale-snapshot revocation case; environment parity and its regressions were also corrected.

[CI 40093696777](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40093696777), source `4bfcc3f`, passed the complete targeted checks, including real PostgreSQL parallel consumption, expiry during a row-lock wait, owner quota races and concurrent/stale-snapshot revocation tests. The existing relay's security/concurrency checks passed in the same job. The candidate schema was installed only into disposable test databases, not the hosted Supabase project.

### Signing contract requiring confirmation

The rendered Connect token reference specifies form encoding and interface `v2`. The general [signature guide](https://developer.webull.com/apis/docs/authentication/signature/) describes `v3` and JSON POST bodies. Both require signing headers, but that general example alone does not establish how the approved Connect form request must be signed. Confirm exact canonicalization, headers/version and error responses with the partner sandbox. The App Secret is signing material, not an HTTP header to forward from the reference widget.

The guide's sandbox/prod H5 browser-login paths and the reference's API authorization-code path are recorded separately. Approval must establish the correct entry/redirect behavior for Crier; parameter preparation is not evidence of a working browser session.

## Validation evidence

Local Deno 2.9.6 verification passed nine synthetic contract test groups, type checking and lint. The existing relay gateway's ten tests and the PostgreSQL-compatible local SQL tests also passed. Tests cover reserved-character form encoding, grant/environment separation, exact expiry and clock boundaries, identity binding, malformed timestamps/callbacks, unknown options and redaction. No network permissions or broker credentials are required by the contract tests. The Supabase workflow now runs them alongside the existing relay checks; this workflow does not deploy anything.

[CI 40090804881](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40090804881), source `3c5ec69`, passed the contract test/type/lint checks, existing gateway checks, PostgreSQL-compatible local tests and real PostgreSQL migration/security/concurrency checks. Independent re-review confirmed all three contract findings below were closed.

Independent review initially found callback URL, decoder-option typo and future-issuance validation gaps. All three received failing regression tests before correction; the nine-group verification above includes those fixes.

## Candidate encrypted token custody

The owner approved this implementation while Webull access remains pending. `supabase/webull-connect/token_vault.ts` encrypts validated OAuth replies with Web Crypto AES-GCM-256, nonextractable keys, independent random 12-byte nonces and 128-bit tags. Authenticated metadata binds the owner, environment, generation, key identifier, identity digest and both expiry deadlines. Keys are supplied by the future protected server configuration; the module reads no environment values and creates no keys on disk.

Decryption rejects changed context or metadata, unknown keys and expired refresh tokens. An expired access token can still be opened for a refresh. Ordinary serialization and runtime inspection redact plaintext tokens and identity; explicit accessors are server-only. Encryption protects persisted data, not a compromised running process or a caller that explicitly logs secrets. Rewrapping under the active key preserves identity and expiry; this helper does not save its result or provide a storage compare-and-set operation.

`supabase/webull-connect/token_store.sql` is a candidate private store outside deployment migrations. Only server-side service-role RPCs can reserve authorization, commit ciphertext, claim refresh, mark an uncertain outcome, read active ciphertext and revoke local custody. Mutations reject fixed-snapshot isolation and use monotonic generations and operation IDs. The database checks envelope structure; the vault verifies its cryptographic authenticity.

A refresh claim returns the previous generation's ciphertext to one worker and advances the stored generation before the broker request. Its result must be sealed under the new generation and committed with the matching operation ID. No timer grants permission to retry a pending or uncertain refresh; reauthorization is required because the broker may have rotated its tokens. Revocation clears ciphertext and retains a tombstone generation so late results cannot reactivate credentials. This local operation does not claim to revoke tokens at Webull or undo an in-flight broker action.

Future authorization must reserve its token generation **before** redirect and bind the operation/generation to the browser authorization session. That association is not yet implemented by the separate session store. The future gateway must derive owner references from verified customer authentication, enforce expiry immediately before use and keep signing, vault and service-role secrets server-side. Token persistence and browser-state persistence alone do not establish a working login flow.

The [custody implementation plan](superpowers/plans/2026-10-24-phase6-token-custody.md) records the scope and remaining integration requirements. The schemas are loaded explicitly only into disposable test databases; no deployment or broker request occurs.

Local verification passed four SQL suites and 32 Deno tests (10 gateway, 9 OAuth contract, 4 state-material and 9 vault tests), plus gateway type checks and lint. Independent review caught an empty-object SQL validation bypass and missing refresh identity retention; both received failing regressions before correction. Text bounds also match the vault's UTF-16 length, whitespace and control-character rules. Real PostgreSQL concurrency results for this slice will be recorded after the targeted CI run.

## Work after Webull approval

1. Confirm granted scopes, approved redirect URI, sandbox credentials, signing rules, request schemas and native-app permission model. Never include partner secrets in binaries or source control.
2. Build a separately isolated authenticated exchange service. Decide token custody, encryption, per-customer authorization, refresh locking, rotation, revocation, audit redaction and deletion before accepting credentials. The existing connection relay remains transport-only.
3. Add browser authorization and deep-link return flows to each client; verify state/binding rejection, account identity and environment separation against the sandbox.
4. Implement account, option-contract resolution, submit/replace/cancel, positions and order reconciliation using approved Connect contracts. Establish what events are available for orders entered through Webull's own app; do not promise submission-time observation before that is proven.
5. Apply the existing intent lifecycle tests and broker UI reconciliation acceptance to Webull. Test token expiry/refresh races and reconnect backfill. Keep execution disabled until those pass; mocks alone do not establish brokerage support.
