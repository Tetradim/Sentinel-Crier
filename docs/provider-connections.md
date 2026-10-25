# Provider connection preparation

This is separately composed server groundwork for Alpaca and Discord OAuth. It is **not deployed**, not connected to the bundled relay, and not an active sign-in option in the customer apps. API-key/webhook setup from Phase F remains the operating path. Webull Connect still needs approval and its own adapter; this code does not implement it.

The Python factory is a reference/test composition. Deploying on the owner's chosen Supabase Free target still needs an Edge-compatible gateway/custody adapter; this preparation does not select or require a new hosting account.

## What is implemented

`OAuthApplication` pins provider hosts and registered HTTPS callbacks. Alpaca Alerts requests default read-only access; Trade requests only `trading`. Tokens are checked for unexpected scopes, then used for a GET to the selected paper/live account. Discord requests only `webhook.incoming` and validates the selected incoming webhook, guild and channel. Exchanges use bounded response bodies, operation/overall timeouts, no redirects and redacted errors. They never submit orders or send Discord messages.

`FlowStore` binds a flow to an authenticated owner and SHA-256 device-proof challenge. It encrypts state and ready credentials with AES-GCM and an externally supplied 32-byte key; context-bound associated data prevents moving ciphertext to another flow. Browser launch and callback require the same independently authenticated browser owner. State, launch ticket and browser binding are one-use; the database stores their hashes. Per-owner and per-challenge active-flow limits apply. A challenge is not a registered device identity; these limits do not replace ingress rate limiting.

`create_oauth_app` prepares begin/browser/callback/status/redeem/cancel routes. Provider credentials return only in the TLS-protected authenticated redemption response, never in the browser/app return URL, status or errors. Redemption requires the device-held proof and consumes ciphertext before returning; a lost redemption response requires a new flow. Interrupted provider exchanges remain `exchanging` (uncertain), with no automatic code retry. An explicit browser denial is `failed`. Cancellation/expiry fence out late results.

Python, Kotlin and Swift share a strict raw return contract and test vectors:

```text
sentinelcrier://oauth/complete?flow=<43 ASCII base64url characters>
```

The URI is only a notification. A one-use in-memory pending record must match the locally captured flow, owner, provider, purpose and environment before a client attempts authenticated redemption. Unknown/duplicate parameters, encoded variants, credentials, fragments and other destinations are rejected. Logout/session change must invalidate pending records. The helpers deliberately do not register OS handlers, launch a network request, install credentials or enable trading/publishing.

## Server composition

Use a dedicated environment:

```sh
python -m venv .venv-oauth
# Activate this environment using the command appropriate to your platform.
python -m pip install -e ".[oauth]"
```

The optional OAuth service pins cryptography 50.0.2. Do not combine this environment with the optional Webull SDK on Python 3.11: that SDK pins cryptography below 42. Existing broker clients and the transport relay do not need the OAuth extra. Automated provider preparation installs `[test,oauth]` in an isolated environment.

An operator composition supplies all dependencies explicitly; there is no auto-enabled CLI endpoint:

```python
import os
from crier.oauth_flows import FlowStore
from crier.oauth_gateway import SupabaseOwnerVerifier, create_oauth_app
from crier.oauth_providers import OAuthApplication

origin = os.environ['CRIER_OAUTH_ORIGIN']  # Exact HTTPS origin, no trailing slash.
verifier = SupabaseOwnerVerifier(
    os.environ['CRIER_AUTH_PROJECT_URL'], os.environ['CRIER_AUTH_PUBLISHABLE_KEY'])
store = FlowStore(os.environ['CRIER_OAUTH_DATABASE'],
                  bytes.fromhex(os.environ['CRIER_OAUTH_KEY_HEX']))
applications = {
    provider: OAuthApplication(provider,
        os.environ[f'CRIER_{provider.upper()}_CLIENT_ID'],
        os.environ[f'CRIER_{provider.upper()}_CLIENT_SECRET'],
        origin + '/oauth/callback/' + provider)
    for provider in ('alpaca', 'discord')
}
app = create_oauth_app(store=store, applications=applications,
    authenticate=verifier, authenticate_browser=verifier.browser,
    public_origin=origin)
```

Keep encryption/application secrets outside the database and client binaries. Provision/back up the key privately; losing or changing it invalidates outstanding encrypted flows. This store handles only short-lived handoff credentials, not long-term refresh-token custody. Browser/client logout integration and customer credential removal remain separate requirements.

Serve behind trusted TLS with query/body access logging disabled. Configure trusted proxy handling explicitly; caller-supplied forwarding headers must not establish trust. Supply ingress rate limits, bounded retention/cleanup scheduling and operational secret controls before deployment. The factory requires both native and browser authentication; it refuses a missing verifier or mismatched callback. The supplied Supabase verifier checks `/auth/v1/user` for an actual nonanonymous user and never uses editable profile metadata as authorization.

A separate authenticated login/BFF must establish the host-only `__Host-crier-session` Secure/HttpOnly/Path=/ browser cookie. Do not pass a customer JWT through a launch URL. Native and browser users must match; possessing a shared launch link is insufficient to authorize someone else's brokerage into the initiator's account. This login/BFF is **not implemented by this preparation**.

## HTTP contract

Native protected calls use `Authorization: Bearer <customer session>`, not the shared relay owner token. POST JSON bodies are limited to 8 KiB, extra fields are rejected, and responses use `Cache-Control: no-store`.

| Route | Inputs | Result |
| --- | --- | --- |
| `POST /oauth/begin` | provider `alpaca`/`discord`, purpose `alerts`/`trade`, environment `paper`/`live`, SHA-256 lowercase-hex `challenge` | Flow ID, expiry, one-use launch URL; Discord purpose is always `alerts`. |
| `GET /oauth/browser?ticket=...` | Independently authenticated matching browser session | Secure flow cookie and pinned-provider redirect. |
| `GET /oauth/callback/{provider}` | Bound state/code or denial, flow cookie, same browser owner; Discord also requires `iss=https://discord.com` | Opaque app return; its presence does not indicate success. |
| `POST /oauth/status` | `flow` | Owner-scoped stage/expiry metadata, no credentials. |
| `POST /oauth/redeem` | `flow`, original 43-character device `proof` | One-use validated credential envelope; caller must verify expected local identity before storage. |
| `POST /oauth/cancel` | `flow`, device `proof` | Sensitive data scrubbed; cancellation metadata remains until expiry/cleanup. |

Flow TTL is at most five minutes. Ready redemption is at most one minute and never extends the original deadline. An interrupted exchange is not made retryable after restart. Explicitly cancel/re-authorize after uncertainty; inspect/revoke provider authorization separately when appropriate. Cancellation removes local flow custody; it is not a remote provider-token revocation or a broker-order cancellation.

## Remaining integration and activation

- Register provider applications and exact HTTPS callbacks, establish callback-domain ownership and configure server-only client secrets. No such provider configuration was performed here.
- Implement and validate the customer login/BFF and native authenticated session lifecycle; wire logout/account changes to pending-flow invalidation.
- Implement the Supabase Edge deployment adapter for the approved hosting target, retaining the separate credential boundary and the same tested ownership/uncertainty rules.
- Wire installed app return handlers, authenticated redemption, Bearer-token broker adapters and secure credential installation on each platform. Preserve existing account/environment pins, unresolved-order journals and destination ownership. Do not replace saved keys/destinations or enable execution/delivery merely because consent succeeded.
- Enforce requested paper/live purpose and verified broker identity again at installation. A selected Discord webhook must follow existing queued/uncertain-message destination safeguards.
- Complete deployment review, live provider-consent interoperability and physical customer acceptance. No real account, broker order, Discord message or OAuth deployment is exercised by the offline tests.

The current scope is provider exchange/custody/HTTP composition and return-contract preparation. The above client/login integration is still implementation work, not something that provider credentials alone can enable.

## References

- [Alpaca OAuth2 and Trading API](https://docs.alpaca.markets/us/docs/using-oauth2-and-trading-api)
- [Discord OAuth2](https://docs.discord.com/developers/topics/oauth2)
- [cryptography release information](https://pypi.org/project/cryptography/)
- [Supabase authenticated user verification](https://supabase.com/docs/reference/javascript/auth-getuser)
