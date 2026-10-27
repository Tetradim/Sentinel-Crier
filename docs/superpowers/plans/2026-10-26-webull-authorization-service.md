# Webull authorization and deployable service assembly

**Goal:** Complete the server authorization lifecycle and service assembly available without activating a real Webull trading adapter.

**Architecture:** A customer-authenticated begin creates a durable single-use browser launch ticket. Browser launch calls the existing coordinator, sets a Secure/HttpOnly/SameSite=Lax cookie and redirects to the exact official Webull login. Callback resolves customer/environment from stored state, not browser parameters. Existing coordinator/vault/RPC code owns one-time exchange, encrypted refresh and revocation. A separate application wrapper supplies strict deployment-prefix handling, customer request admission and unavailable trading defaults.

Native consent may be available while trading remains unavailable. Tokens never return to the native client. The first deployment must remain disabled until Webull approval and protected configuration are supplied. No order/resource endpoint is invented.

- [x] Add failing behavioral tests for browser cookie binding, one-use launch, callback replay, refresh/revoke and secret-free replies.
- [x] Implement authorization runtime using the existing coordinator/vault and durable browser flow RPCs.
- [x] Add server-only signed token exchange with pinned endpoint, bounded response and no retry.
- [x] Add per-customer durable admission, service configuration validation and deployable Edge entry point.
- [x] Adapt iPhone consent to the exact configured gateway launch URL while retaining trading-disabled checks.
- [x] Run SQL/gateway/native verification, document precise source results and remaining approved trading-adapter work; commit/push main.

Customer-ready handoff still requires the concrete approved account/contract/order adapter, its long-only reservations, deployed operator configuration, Webull sandbox acceptance and signed/physical iPhone acceptance. Windows technical logging/support export is now implemented separately; independent remote outage notification remains unfinished.

Automated source acceptance: [handoff operations evidence](../../acceptance/2026-10-26/customer-handoff-ops/README.md). This completes this plan's implementation scope, with the external and trading-adapter exclusions above retained.
