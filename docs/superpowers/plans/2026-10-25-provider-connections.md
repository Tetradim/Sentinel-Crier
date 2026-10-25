# Phase G — Provider connection preparation

> Use subagent-driven-development for independent implementation and review; retain main-only direct commits.

**Goal:** Prepare authenticated Alpaca/Discord authorization-code handling and device-bound return contracts, tested without provider registrations, real credentials or deployment.

**Approved design:** Phase G in customer-ease-plan.md. Keep application secrets server-side, bind each flow to an authenticated owner and initiating device proof, separate read-only Alerts from trading scope, and never treat provider consent as execution or publishing permission. The existing transport-only Supabase relay remains unchanged. This is a separately composed service, not a new credential-custody responsibility silently added to that relay.

**Provider references checked October 25:** [Alpaca OAuth](https://docs.alpaca.markets/us/docs/using-oauth2-and-trading-api) documents default read-only access, `trading` scope, explicit paper/live environment, backend form token exchange and Bearer authentication. [Discord OAuth](https://docs.discord.com/developers/topics/oauth2) documents `webhook.incoming`, form token exchange and required issuer verification for multi-provider callbacks. No Webull protocol is invented while its approval remains pending.

## Implementation tasks

- [ ] G.1 Provider adapters: pinned authorization/token/account hosts; exact registered callback; minimal scopes; bounded HTTP exchanges; validate token type/scopes, account or webhook identity and generic redacted errors. Only mocked HTTP; no orders or message sends.
- [ ] G.2 Durable flow custody: one-use browser launch, secure-cookie callback binding, atomic callback claim, expiry/replay/owner isolation, encrypted short-lived grants, one-use authenticated device-proof redemption, cancel/cleanup and uncertainty after interrupted exchange. No plaintext token persistence or automatic exchange retries.
- [ ] G.3 Authenticated HTTP composition: require an explicit owner verifier and server-only encryption/application configuration; browser callbacks return only an opaque flow ID; no token/code in app return URLs. Security headers, query/body validation, uniform errors and isolated integration tests. Not installed into the existing relay or console by default.
- [ ] G.4 Native return contracts: strict shared URI parsing and pending-flow validation on Python/Windows, Swift and Kotlin with synthetic fixtures. Returns must not save credentials or enable execution; complete broker-token credential installation and customer-login/UI wiring are tracked separately if unavailable in the bounded preparation.
- [ ] G.5 Independent review, full backend and relevant native checks, operator/configuration documentation and source-bound evidence. Describe implemented composition separately from deployed/customer-ready OAuth.

## Flow and custody

An authenticated begin call supplies provider, purpose, paper/live environment and a SHA-256 challenge of a device-held random proof. The service creates an opaque flow ID/state and a one-use browser-launch ticket. Opening that ticket sets a Secure/HttpOnly/SameSite=Lax cookie scoped to this flow and redirects only to a pinned provider host. Callback validates provider/issuer/state/cookie/expiry, atomically claims the exchange and never retries an ambiguous exchange. Validated credentials are encrypted at rest with an explicit external 32-byte server key and short redemption deadline. Browser return contains only `sentinelcrier://oauth/complete?flow=<43-character base64url ID>`; authenticated redemption additionally requires the device proof. Redeem/cancel/expiry remove credential ciphertext. Replays, wrong owner/device, late exchange results and configuration mix-ups cannot change another flow.

The authenticated owner comes from a trusted server verifier, never request JSON or editable profile metadata. Factories must fail closed without required configuration. Live activation still needs a registered provider app, exact callback ownership, authenticated customer sessions and native credential installation. Physical operation, provider consent, real Discord messages and broker orders are excluded from this preparation.
