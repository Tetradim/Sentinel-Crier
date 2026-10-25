# Provider connections

Phase G.6 implements a separate Supabase OAuth service and customer sign-in on Windows, Android and iOS. The service is **not deployed**. Provider consent remains unavailable until the operator registers the applications, configures the service and completes interoperability checks. Existing API-key and manual webhook setup remains usable. Webull Connect approval and its adapter remain separate work.

## Customer flow

1. Choose Alerts, Trade or Follow and the paper/live environment in Crier.
2. Open Provider connections and check service availability. An unavailable service leaves manual setup available.
3. Sign in or create a Crier customer account. Email-confirmation requirements come from the configured Supabase project. The browser may ask for the same Crier login again.
4. Choose Alpaca or Discord and complete consent on the official provider website. Crier never asks for the brokerage password.
5. Return to the originating app. The app validates a one-use device-bound receipt, customer, project, provider, purpose and environment.
6. Windows verifies and saves the matching returned connection; iOS and Android present a separate installation action. Reconnect, preview/test and enable explicitly. Account verification, Discord preview/test, monitoring permission and trading permission remain separate steps. Consent does not start workers or place an order.

Alpaca Alerts requests read access; Trade requests `trading`. Discord requests only `webhook.incoming` and records the selected guild/channel. OAuth credentials are stored in device-protected storage with customer and exact service provenance. Manually supplied API keys remain a separate mode.

Logout stops or drains workers and invalidates pending handoffs. Android and iOS remove installed OAuth secrets while preserving journals and delivery evidence. Windows retains account-bound recovery credentials in encrypted storage and quarantines them until the original customer signs in again. Logout is not provider-side token revocation and does not cancel existing brokerage orders. Revoke access at the provider separately when required.

Changing Discord destinations remains blocked by unresolved messages. Changing brokerage accounts cannot discard unresolved orders or reconciliation evidence. An ordinary settings save must preserve OAuth ownership markers for an unchanged destination. Missing legacy provenance fails closed.

## Implemented service boundary

The production-target source is `supabase/functions/crier-oauth/index.ts`, composed from `supabase/provider-connect/`. It is separate from the existing `crier` transport relay; shared relay tokens cannot authenticate customer OAuth requests.

The exact trusted base is:

```text
https://<20-lowercase-letter-project-reference>.supabase.co/functions/v1/crier-oauth
```

The gateway accepts the public Supabase function path and its internal function prefix, while deriving redirects and callbacks only from configured project identity. Native clients reject alternate schemes, projects, paths and untrusted redirects.

A service-only PostgreSQL RPC in `supabase/provider-connect/flow_store.sql` owns custody transitions. The candidate SQL is intentionally outside automatic migrations. Row locking enforces one-use launch/redemption, same-owner browser binding, cancellation and expiry, with clock sampling after lock acquisition. Owner/challenge quotas and bounded cleanup apply. AES-GCM envelopes bind ciphertext to the flow and purpose; encryption keys remain external to the database.

Browser login uses an HttpOnly Secure host cookie, exact Origin, hidden proof and durable one-use CSRF claims. Native login returns a session without installing browser cookies. Both browser and native identity must match: sharing a launch link does not authorize a different customer's account.

## HTTP contract

All protected native calls use a customer session Bearer token verified with Supabase Auth. JSON bodies are bounded to 8 KiB; provider responses are bounded to 64 KiB. Exchange operations and overall requests have timeouts, no redirects and redacted failures. Responses use no-store.

| Route | Result |
| --- | --- |
| `GET /oauth/capabilities` | Pinned service/project identity and available providers. |
| `POST /auth/login`, `/auth/signup`, `/auth/refresh` | Native customer session; signup can require email confirmation. |
| `GET/POST /auth/browser` | Same-customer browser sign-in with CSRF protection. |
| `POST /oauth/begin` | Owner-bound flow, expiry and one-use browser launch URL. Requires provider, purpose, environment and SHA-256 device-proof challenge. |
| `GET /oauth/browser?ticket=...` | Same-owner browser binding and official provider redirect. |
| `GET /oauth/callback/{provider}` | Bound state/cookie/code or denial, followed by an opaque app return. Discord also requires its expected issuer. |
| `POST /oauth/status` | Owner-scoped stage/expiry metadata without credentials. |
| `POST /oauth/redeem` | One-use credential envelope, requiring the original device proof. |
| `POST /oauth/cancel` | Scrub flow custody and fence late results. |

The app return contains only:

```text
sentinelcrier://oauth/complete?flow=<43 ASCII base64url characters>
```

It is a notification, not proof of success. Unknown or duplicate parameters, encoded variants, fragments and credential-bearing returns are rejected. The originating process must retain its pending owner/provider/purpose/environment and secret device proof. Process loss requires a new flow.

Flow TTL is at most five minutes. Ready redemption is at most one minute and cannot extend the original deadline. Ambiguous exchange remains `exchanging`; ambiguous redemption is not retried. Cancel and start a new flow after uncertainty. Custody cancellation is neither remote token revocation nor brokerage order cancellation.

## Activation prerequisites

No deployment, provider registration, email delivery, live consent, broker order or Discord message is performed by the automated tests.

Before activation, an operator must:

- Register Alpaca and Discord applications with exact callbacks `<base>/oauth/callback/alpaca` and `<base>/oauth/callback/discord`, and complete any provider approval/domain requirements.
- Review and apply the candidate SQL to the intended Supabase project. Keep private tables and RPC permissions service-only.
- Supply `CRIER_OAUTH_ENCRYPTION_KEY` (canonical unpadded base64url of 32 random bytes), `CRIER_OAUTH_KEY_ID`, `CRIER_AUTH_PUBLISHABLE_KEY`, and the enabled providers' `CRIER_ALPACA_CLIENT_ID`/`CRIER_ALPACA_CLIENT_SECRET` or `CRIER_DISCORD_CLIENT_ID`/`CRIER_DISCORD_CLIENT_SECRET`. Supabase supplies the project URL and service-role environment. Never put service-role/provider secrets or custody keys in clients or source control.
- Deploy the separate `crier-oauth` function with its supplied configuration. JWT verification at the platform gateway is disabled because this handler independently verifies customer sessions; that must not be confused with anonymous access to protected endpoints.
- Confirm capabilities, authenticated/native and browser ownership, real consent interoperability, expiry/cancellation and device return behavior on the target deployment. Establish ingress rate limiting, cleanup scheduling and key/secret recovery procedures before customer activation. Per-flow quotas alone are not an ingress rate limiter.
- Complete signing, distribution and physical acceptance for the intended platforms. iOS still obeys its foreground/background limits; OAuth does not create an always-on phone watcher.

An incomplete operator configuration returns HTTP 503. The existing transport relay is unaffected.

## Automated verification

```sh
npm ci --prefix supabase/tests
npm test --prefix supabase/tests
node --experimental-strip-types supabase/tests/provider-edge-integration.mjs
npm exec --package deno@2.9.6 -- deno test supabase/provider-connect
npm exec --package deno@2.9.6 -- deno check supabase/functions/crier-oauth/index.ts
```

`provider-edge-tests.yml` also runs permissions and concurrent one-use transitions against real PostgreSQL 17. Synthetic gateway acceptance uses the actual gateway, WebCrypto and SQL with injected external HTTP. Platform workflows verify native source, app packaging and mocked customer journeys.

The Python OAuth composition remains a reference/test adapter. Its optional `[oauth]` extra pins cryptography 50.0.2; use a separate environment from the optional Webull SDK on Python 3.11, which requires cryptography below 42. Default broker/relay clients do not need this extra.
