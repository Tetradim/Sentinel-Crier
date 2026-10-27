# Webull authorization service assembly

The deployable `crier-webull-host` Edge Function now composes browser authorization, the existing encrypted token coordinator/vault, signed token exchange/refresh, generation-fenced server credential access and durable customer request admission. This is separate from the unchanged instruction relay. **No account/contract/order resource adapter is installed, and this work does not enable real Webull trading.**

## What is implemented

- Native authenticated begin returns a single-use gateway launch ticket, never an application secret or broker token.
- Browser launch consumes the ticket, starts the coordinator, sets a flow-specific Secure/HttpOnly/SameSite=Lax cookie and redirects to the exact official Webull login for the source environment.
- Callback resolves the owner/environment from private stored state and validates the browser binding through the coordinator. Callback queries cannot select another customer. Replayed callbacks cannot exchange a code twice.
- Status, refresh and local revocation require verified customer sessions. Refresh rotates encrypted custody; uncertain grants are not automatically retried. Revocation invalidates unused browser flows before clearing custody.
- Trusted resource adapters can borrow server-only credential access. Each actual request rechecks the active generation/expiry and reserves admission. A retained lease cannot bypass later revocation.
- Private SQL provides rolling sixty-second admission, with separate customer HTTP and actual Webull request budgets. The application uses 60 HTTP and 80 Webull requests per customer per window. Future resource adapters must use the credential request boundary for every outbound call; do not hide multiple requests inside one admission.
- The iPhone can distinguish authorization availability from trading availability. Its consent URL must be the exact configured gateway launch URL. An authorization-only service cannot enable source orders.

## Operator prerequisites

Webull approval and issued application permissions remain required for actual consent. Register this exact callback for the chosen project:

```text
https://YOUR_PROJECT_REF.supabase.co/functions/v1/crier-webull-host/v1/connect/callback
```

Crier customer sign-in must be activated against the same Supabase Auth project. The existing native Provider connections screen supplies that customer session. Keep broker client/signing secrets and vault keys exclusively in protected server configuration.

Required runtime names supplied by the platform/operator:

| Name | Purpose |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Platform project and privileged server RPC access |
| `CRIER_AUTH_PUBLISHABLE_KEY` or platform `SUPABASE_ANON_KEY` | Remote customer-session verification |
| `CRIER_WEBULL_INTEGRATION_APPROVED` | Exact `true` only after actual approval; absent/`false` leaves authorization disabled |
| `CRIER_WEBULL_ENVIRONMENT` | Explicit `sandbox` or `production` |
| `CRIER_WEBULL_CLIENT_ID`, `CRIER_WEBULL_CLIENT_SECRET`, `CRIER_WEBULL_SCOPE` | Issued OAuth application configuration |
| `CRIER_WEBULL_APP_KEY`, `CRIER_WEBULL_APP_SECRET` | Issued request-signing configuration |
| `CRIER_WEBULL_VAULT_KEY`, `CRIER_WEBULL_VAULT_KEY_ID` | Protected 32-byte base64url AES key and its identifier |
| `CRIER_WEBULL_PREVIOUS_VAULT_KEYS` | Optional JSON map of up to eight previous key IDs/keys, retained during rotation |

Do not paste secret values into chat, logs, screenshots, the repository or native app settings. Preflight prints only safe state and callback metadata:

```powershell
npm exec --yes --package deno@2.9.6 -- deno run --allow-env supabase/webull-host/preflight.ts
```

Preflight makes no network calls and cannot prove approval, installed schema, registered callbacks or provider compatibility. Retaining old keys permits existing custody to be decrypted while refresh writes the active key. Full rewrapping uses the existing server operations module; do not remove an old key merely because the active ID changed.

## Schema and deployment

SQL remains deliberately outside automatic deployment migrations. Stage/review versioned migrations in an isolated test project before installation. Existing candidate stores use creation statements that are not intended to be rerun blindly. Required installation order:

1. `supabase/webull-connect/session_store.sql`
2. `supabase/webull-connect/token_store.sql`
3. `supabase/webull-connect/authorization_flow.sql`
4. `supabase/webull-connect/operations.sql`
5. `supabase/webull-host/ledger.sql`
6. `supabase/webull-host/browser_store.sql`

After schema review and protected configuration, the prepared function can be deployed using the existing authenticated CLI session:

```powershell
npx --yes supabase@2.122.0 functions deploy crier-webull-host --project-ref YOUR_PROJECT_REF --use-api --no-verify-jwt
```

The function validates customer sessions itself; browser launch/callback have no platform bearer header and use their stored ticket/state/cookie checks. Disabling the platform JWT gate does not make native operations anonymous. Do not use `--prune` or deploy unrelated functions to activate this module.

Without approved authorization configuration, the function advertises unavailable capabilities. Even with successful consent, its included entry point has **no trading adapter**. Only an explicit reviewed resource binding in code can enable account/order capabilities; setting an environment flag cannot do so.

This change does not deploy the function, install the schema, configure secrets or submit another Webull application.

## Acceptance and recovery

The synthetic full-flow test traverses real HTTP routing, coordinator, encryption and SQL with intercepted Auth/Webull responses. CI additionally runs real PostgreSQL worker-contention checks. These do not establish vendor or physical acceptance.

Before customer handoff, test real sandbox consent, account identity, expiry/refresh, denied consent, callback replay, local removal and reauthorization. Verify old browser links cannot restore locally removed access. Protect platform/proxy logs from recording authorization headers, launch tickets, state/code query values or token bodies.

An uncertain exchange/refresh requires status inspection and fresh consent rather than repeating a rotating grant. Local removal clears Crier custody; it does not claim remote Webull grant revocation or cancel broker orders. Disabling deployment/configuration also does not constitute remote revocation or liquidation.

The approved account/contract/order adapter, long-only source reservations, actual service activation and real Webull → Alpaca-paper acceptance remain unfinished. Unattended error logging/notifications remain the next separate hardening item. See [route status](webull-iphone-host.md).
