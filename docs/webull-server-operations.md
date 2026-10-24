# Candidate Webull server components

These components are server libraries and candidate SQL, not a deployed broker gateway. They implement the autonomous plan's coordination and recovery scope with injected authentication/signing ports. No Webull login or trading capability has been added to a released client.

## Composition and configuration

`coordinator.ts` exports `createCoordinator`. Supply a trusted `verifyPrincipal` that verifies a real customer session and returns its server-derived owner reference; never implement it by reading an owner identifier from an unverified request. `rpc_store.ts` exports `createRpcStore`, which adapts an authenticated server-side RPC client to the compound authorization and token procedures. Do not pass a service-role credential to a browser or native client.

The coordinator requires explicit `integrationApproved` and `signingReady` values of true, an environment, client ID/secret, scopes, an exact configured HTTPS callback and the matching documented Webull browser entry. Unknown fields, invalid callbacks, unsupported entries and missing readiness are rejected. The fixture's true values only permit synthetic tests; they do not establish Webull approval. This is structural configuration validation, not verification of vendor-issued credentials or scopes.

`transport(request, signal)` is a trusted injected dispatcher. It receives the pinned token endpoint and explicitly serialized form, must apply the approved Connect signature, respect the abort signal, bound the HTTP response body and **never retry** authorization-code or rotating refresh grants automatically. No concrete signer or broker HTTP transport is included while that contract remains unresolved. The coordinator additionally bounds decoded reply fields and imposes a 1–30,000 ms dispatch timeout (default 10,000 ms). An ignored abort cannot resume a timed-out coordinator operation and commit a late response.

The vault is supplied with nonextractable AES-GCM keys from protected server configuration. Native clients must receive neither those keys nor the broker token objects. The future HTTP handler must also implement request limits, verified customer authentication, exact redirect configuration, Secure/HttpOnly browser binding and platform return behavior. None of those HTTP/browser components is deployed by these libraries.

## Normal lifecycle

1. `begin(authInput)` verifies the principal and atomically reserves a generation and pending browser session. Its result exposes the authorization URL and browser binding only through explicit methods; default serialization redacts them.
2. The future handler directs the customer to `authorization.url()` and stores `authorization.browserBinding()` in a protected cookie. It must not log either value.
3. `callback(authInput, {state, browserBinding, code})` validates and consumes the matching session once, invokes the signed transport, validates the broker reply, encrypts it and commits with the reserved generation/operation.
4. `refresh(authInput)` claims the active generation once, decrypts the old custody, checks the returned identity, and commits the encrypted replacement under the new generation. Concurrent callers cannot both dispatch the same rotating token.
5. `revoke(authInput)` clears pending browser sessions and local token custody atomically. Late results fail their generation fence. Local revocation does not claim remote Webull revocation or cancellation of an in-flight request.

Public coordinator results contain state, generation and deadlines rather than raw tokens. `operations.status` supplies recovery-oriented states such as `refresh_required`, `refresh_pending` and `reauthorization_required`; these are library results, not newly deployed client screens.

## Uncertain outcomes and recovery

An uncertain code exchange or refresh transitions the matching pending operation to `unknown` where possible. If persistence itself fails, the stored pending state remains nonretryable. A late response cannot restart the timed-out coordinator continuation. Do not clear a pending marker, restore an old ciphertext or resubmit an old refresh grant to recover a crash.

Recovery is an explicit new `begin` followed by a fresh browser authorization. It advances the generation and invalidates the old reservation. The offline acceptance runner verifies this sequence against actual SQL after a lost refresh response. A stale worker cannot reactivate custody after the new authorization or revocation.

## Key rotation

`operations.ts` exports `createOperations`. Its `rotateKey(authInput)` verifies the owner, reads active custody, rewraps with the configured active vault key and calls the SQL compare-and-set operation. The old and new envelopes must retain the same identity and expiry deadlines. The SQL generation remains unchanged because the wrapping is bound to that generation; the exact expected envelope prevents stale overwrites by competing rotations, refresh claims or revocations.

Keep both old and new vault keys configured while rewrapping existing rows. A `stale` result means another operation won: reread current status instead of writing an old replacement again. Missing keys, expired refresh tokens and uncertain states require authorization recovery. Remove an old key only after an operator has verified that active custody no longer needs it; no automated key deletion or real key provisioning is performed here.

## Cleanup and audit

`operations.cleanup(authInput, limit)` requires a separate trusted operator verifier and a limit of 1–500. SQL deletes only expired browser sessions using ordered row locks with `SKIP LOCKED`. Linked reservation metadata cascades with those sessions. Active sessions and token generation tombstones remain. Locked expired rows may be handled by a later bounded invocation; cleanup does not authorize a retry of broker work.

The optional audit sink receives only schema, action, outcome, environment and time. It receives no owner, identity, code, token, browser binding or encrypted envelope. Delivery is best effort: synchronous or asynchronous sink failures cannot reverse a completed mutation or trigger its retry. This hook is not a durable audit log or monitoring service. Persist it through an appropriate protected operator sink when a gateway is deployed.

## Offline verification

Use Node 24 and the pinned test dependency lockfile:

```powershell
npm ci --prefix supabase/tests
npm test --prefix supabase/tests
npm exec --yes --package deno@2.9.6 -- deno test supabase/webull-connect supabase/functions/crier/gateway_test.ts
node supabase/tests/offline-acceptance.mjs > webull-offline-acceptance.json
```

The Node acceptance runner creates an in-memory PostgreSQL-compatible database, loads candidate stores explicitly, and uses service-role RPCs, the real coordinator/adapter and real vault encryption with synthetic keys. Its nine scenarios cover exchange/refresh/replay, authentication/binding rejection, revoke during exchange, lost refresh recovery, ignored abort, key rotation, bounded cleanup, stale rotation and unapproved configuration.

The JSON report distinguishes implemented and synthetically integrated components from deployment and broker acceptance. Dirty relevant files are attributed to the working tree rather than to HEAD alone. CI uploads a report artifact tied to its clean checkout. The real PostgreSQL 17 job separately tests concurrent workers using dblink. Neither form of evidence proves vendor acceptance, physical-device behavior or live broker correctness.
