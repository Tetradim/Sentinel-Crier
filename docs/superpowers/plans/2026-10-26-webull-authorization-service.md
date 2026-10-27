# Webull authorization and deployable service assembly

**Goal:** Complete the server authorization lifecycle and service assembly available without activating a real Webull trading adapter.

**Architecture:** A customer-authenticated begin creates a durable single-use browser launch ticket. Browser launch calls the existing coordinator, sets a Secure/HttpOnly/SameSite=Lax cookie and redirects to the exact official Webull login. Callback resolves customer/environment from stored state, not browser parameters. Existing coordinator/vault/RPC code owns one-time exchange, encrypted refresh and revocation. A separate application wrapper supplies strict deployment-prefix handling, customer request admission and unavailable trading defaults.

Native consent may be available while trading remains unavailable. Tokens never return to the native client. The first deployment must remain disabled until Webull approval and protected configuration are supplied. No order/resource endpoint is invented.

- [ ] Add failing behavioral tests for browser cookie binding, one-use launch, callback replay, refresh/revoke and secret-free replies.
- [ ] Implement authorization runtime using the existing coordinator/vault and durable browser flow RPCs.
- [ ] Add server-only signed token exchange with pinned endpoint, bounded response and no retry.
- [ ] Add per-customer durable admission, service configuration validation and deployable Edge entry point.
- [ ] Adapt iPhone consent to the exact configured gateway launch URL while retaining trading-disabled checks.
- [ ] Run SQL/gateway/native verification, document precise source results and remaining approved trading-adapter work; commit/push main.

Customer-ready handoff still requires the concrete approved account/contract/order adapter, its long-only reservations, deployed operator configuration, Webull sandbox acceptance and signed/physical iPhone acceptance. Unattended logging/alerting remains a separate next work item.
