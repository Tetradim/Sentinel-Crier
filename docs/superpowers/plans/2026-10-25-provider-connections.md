# Phase G — Provider connection preparation

> Use subagent-driven-development for independent implementation and review; retain main-only direct commits.

**Goal:** Prepare authenticated Alpaca/Discord authorization-code handling and device-bound return contracts, tested without provider registrations, real credentials or deployment.

**Approved design:** Phase G in customer-ease-plan.md. Keep application secrets server-side, bind each flow to an authenticated owner and initiating device proof, separate read-only Alerts from trading scope, and never treat provider consent as execution or publishing permission. The existing transport-only Supabase relay remains unchanged. This is a separately composed service, not a new credential-custody responsibility silently added to that relay.

**Provider references checked October 25:** [Alpaca OAuth](https://docs.alpaca.markets/us/docs/using-oauth2-and-trading-api) documents default read-only access, `trading` scope, explicit paper/live environment, backend form token exchange and Bearer authentication. [Discord OAuth](https://docs.discord.com/developers/topics/oauth2) documents `webhook.incoming`, form token exchange and required issuer verification for multi-provider callbacks. No Webull protocol is invented while its approval remains pending.

## Implementation tasks

- [x] G.1 Provider adapters: pinned authorization/token/account hosts; exact registered callback; minimal scopes; bounded HTTP exchanges; validate token type/scopes, account or webhook identity and generic redacted errors. Only mocked HTTP; no orders or message sends.
- [x] G.2 Durable flow custody: one-use browser launch, secure-cookie callback binding, atomic callback claim, expiry/replay/owner isolation, encrypted short-lived grants, one-use authenticated device-proof redemption, cancel/cleanup and uncertainty after interrupted exchange. No plaintext token persistence or automatic exchange retries.
- [x] G.3 Authenticated HTTP composition: require an explicit owner verifier and server-only encryption/application configuration; browser callbacks return only an opaque flow ID; no token/code in app return URLs. Security headers, query/body validation, uniform errors and isolated integration tests. Not installed into the existing relay or console by default.
- [x] G.4 Native return contracts: strict shared URI parsing and pending-flow validation on Python/Windows, Swift and Kotlin with synthetic fixtures. Returns must not save credentials or enable execution; complete broker-token credential installation and customer-login/UI wiring are tracked separately if unavailable in the bounded preparation.
- [x] G.5 Independent review, full backend and relevant native checks, operator/configuration documentation and source-bound evidence. Describe implemented composition separately from deployed/customer-ready OAuth.

## Flow and custody

An authenticated begin call supplies provider, purpose, paper/live environment and a SHA-256 challenge of a device-held random proof. The service creates an opaque flow ID/state and a one-use browser-launch ticket. Opening that ticket sets a Secure/HttpOnly/SameSite=Lax cookie scoped to this flow and redirects only to a pinned provider host. Callback validates provider/issuer/state/cookie/expiry, atomically claims the exchange and never retries an ambiguous exchange. Validated credentials are encrypted at rest with an explicit external 32-byte server key and short redemption deadline. Browser return contains only `sentinelcrier://oauth/complete?flow=<43-character base64url ID>`; authenticated redemption additionally requires the device proof. Redeem/cancel/expiry remove credential ciphertext. Replays, wrong owner/device, late exchange results and configuration mix-ups cannot change another flow.

Browser launch and callback additionally authenticate the browser user independently and require the original owner before any state transition. The launch ticket alone is insufficient: this prevents an attacker from sharing their flow link and capturing another customer's broker consent. Limits are per owner and per proof challenge; no authenticated stable-device quota is claimed.

The authenticated owner comes from a trusted server verifier, never request JSON or editable profile metadata. Factories must fail closed without required configuration. Live activation still needs a registered provider app, exact callback ownership, authenticated customer sessions and native credential installation. Physical operation, provider consent, real Discord messages and broker orders are excluded from this preparation.

## Remaining customer integration

- [ ] G.6 Implement the Supabase Edge deployment adapter, login/BFF and native session lifecycle, installed callback handlers, authenticated redemption and secure Bearer-token/Discord destination installation with identity/journal checks. These are remaining source integration tasks; adding provider keys alone does not complete them. Preserve explicit publishing/trading permission and current API-key recovery throughout.

The [operator guide](../../provider-connections.md) documents current composition and remaining work. This plan does not claim working customer OAuth while G.6 remains open.

## Verification evidence

Implementation source `e36d68f` passed **765 local Python tests/one optional SDK skip** in the isolated OAuth environment and **172 focused OAuth cases**. The existing Webull environment retains its dependency versions; the default profile skips custody/gateway modules when the OAuth extra is absent.

Independent reviews led to mandatory same-owner browser authentication, conservative uncertainty after an interrupted exchange, accurate per-challenge quota naming and byte-exact Swift owner matching. The initial Windows matrix found an unrelated collection-time timestamp fixture that stopped being future-dated during the larger suite. Source `c7ac145` computes it at execution; **193 mirror/OAuth tests passed locally**, and the corrected [matrix 40166904590](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40166904590) passed Windows Python 3.11 (**765/one skip**) and Linux Python 3.11/3.12 (**746/20 skips each**). Production freshness behavior did not change.

The implementation revision also passed [72 Android tests/debug APK packaging](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40166643423), [iOS simulator/unsigned hardware archive](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40166645228), and [98 iOS tests/default backend](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40166646930). The default Linux profile passed 677/22 skips, including the explicitly absent optional OAuth dependency. The dedicated matrix executes those OAuth tests.

The [source-bound report](../../acceptance/2026-10-25/provider-preparation/source-evidence.json) records exact revisions, counts, the initial fixture failure and unresolved integration scope. No provider consent, remote deployment, broker order, Discord message or physical acceptance was performed. G.1–G.5 preparation is verified; G.6 and live activation remain open.
