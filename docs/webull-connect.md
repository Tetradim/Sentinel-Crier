# Webull Connect integration status

October 23, 2026: the owner confirms the existing Connect application is still awaiting approval. Do not submit another application. Webull login and trading are not available in released Crier clients.

## Implemented groundwork

`crier/webull_connect_sessions.py` is an isolated server-side authorization-session primitive. It creates independent random state and browser-binding secrets, stores only their SHA-256 hashes, and binds redemption to an authenticated customer identity, sandbox/production environment and configured HTTPS callback. Sessions expire after five minutes; matching redemption deletes the session in one transaction. Invalid attempts leave the legitimate session intact. Concurrent callbacks cannot both succeed. A gateway must use a new session after any failed or uncertain code exchange.

This module is not connected to the apps, HTTP endpoints, Webull or the deployed Supabase relay. It holds no broker tokens. Its SQLite persistence supports restart and local concurrency testing; it is not a storage option for ephemeral Supabase Edge Functions. A hosted implementation will need equivalent transactional PostgreSQL behavior and deployment tests.

The future gateway must authenticate the customer when starting authorization, bind the second secret to a Secure/HttpOnly browser cookie, enforce request limits, check the exact registered redirect and verify the callback before exchanging its code. The user identity must come from the authenticated session, never a callback query parameter. Cookie policy and browser return behavior must be tested on all platforms. State alone is not customer authentication.

## Documentation findings

Webull's [OAuth integration guide](https://developer.webull.com/apis/docs/connect-api/authentication/) requires server-held application secrets. Codes are single-use and short-lived; refresh rotates both tokens. Use the returned expiry values, not hard-coded token lifetimes. The five-minute Crier login session does not extend Webull's authorization-code validity.

The [Connect overview](https://developer.webull.com/apis/docs/connect-api/about-connect-api/) separates sandbox and production services and requires following Connect-specific resource paths and headers. The existing `crier/webull.py` SDK observer implements the separate Trading API flow; its credentials and payload assumptions cannot establish Connect compatibility.

Public [authorization-code](https://developer.webull.com/apis/docs/reference/connect-api/get-authorization-code/) and [token](https://developer.webull.com/apis/docs/reference/connect-api/create-and-refresh-token/) pages identify endpoint paths, but the text available during this review did not expose the full request/response schemas. No token payload or signing implementation has been guessed.

## Work after approval

1. Confirm granted scopes, approved redirect URI, sandbox credentials, signing rules, request schemas and native-app permission model. Never include partner secrets in binaries or source control.
2. Build a separately isolated authenticated exchange service. Decide token custody, encryption, per-customer authorization, refresh locking, rotation, revocation, audit redaction and deletion before accepting credentials. The existing connection relay remains transport-only.
3. Add browser authorization and deep-link return flows to each client; verify state/binding rejection, account identity and environment separation against the sandbox.
4. Implement account, option-contract resolution, submit/replace/cancel, positions and order reconciliation using approved Connect contracts. Establish what events are available for orders entered through Webull's own app; do not promise submission-time observation before that is proven.
5. Apply the existing intent lifecycle tests and broker UI reconciliation acceptance to Webull. Test token expiry/refresh races and reconnect backfill. Keep execution disabled until those pass; mocks alone do not establish brokerage support.
