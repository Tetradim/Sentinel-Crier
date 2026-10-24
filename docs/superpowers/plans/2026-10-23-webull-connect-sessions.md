# Webull Connect authorization session groundwork

**Goal:** Implement the local, server-side authorization-state boundary described by Phase 6 without enabling Webull or inventing its token contract.

**Architecture:** A separate SQLite session store holds only hashes of random state and browser-binding secrets, an opaque customer identity, the pinned environment and HTTPS callback, and expiry. Callback acceptance consumes a matching session atomically. This module has no HTTP routes, token exchange, broker requests, or connection to the deployed relay. The future service must authenticate the customer at session creation and bind the second secret to a Secure, HttpOnly browser cookie. It must never accept customer identity from an unauthenticated callback.

**Scope:** Customer access remains pending Webull approval. This is groundwork, not a working login feature. Application secrets, access tokens and refresh tokens are outside this store. Do not embed partner secrets in device apps. The token endpoint schema and granted scopes must be verified with approved sandbox access before building exchange or order APIs.

## Steps

- [x] Write failing tests for isolation, restart, one-use consumption, expiration, concurrent callbacks, malformed configuration and secret redaction.
- [x] Add `crier/webull_connect_sessions.py` with bounded session lifetime, fixed environments, exact configured callback matching and transactional consumption. Invalid attempts must not consume a valid session.
- [x] Run focused tests, then the complete Python suite. Review the diff for secret leakage and unintended enablement.
- [x] Document current approval status, integration boundaries and remaining sandbox acceptance; correct old monitor documentation that implies Crier never submits Alpaca orders.
- [ ] Commit and push directly to main as instructed.

## Acceptance

Two concurrent callback attempts produce exactly one acceptance. Wrong browser binding, customer, environment or callback cannot redeem or destroy the correct session. Expired sessions and replays fail. Database inspection and object representations contain no raw state or browser secret. No live brokerage or hosted relay changes occur.

Verified locally: 476 Python tests passed, including 23 authorization-session tests. One existing FastAPI/Starlette HTTPX deprecation warning remains. The initial focused run failed because the new module did not exist; the implementation then passed. These are local primitive tests, not Webull sandbox or deployed gateway acceptance.
