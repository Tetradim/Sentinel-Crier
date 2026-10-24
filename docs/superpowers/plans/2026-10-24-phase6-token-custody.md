# Phase 6: isolated token custody and refresh fencing

The owner approves implementation; Webull's application response is still pending. This slice prepares server-only primitives without accepting credentials, creating endpoints or deploying a schema. It does not establish working Webull login or trading.

## Approved design

1. Encrypt validated OAuth replies using Web Crypto AES-GCM-256, nonextractable keys, fresh 96-bit nonces and 128-bit tags. Authenticate the owner, environment, monotonic generation, key identifier, identity digest and expiry metadata. Keep secrets behind explicit accessors; redact ordinary serialization and inspection. Support key rewrapping without extending broker validity.
2. Prepare a private candidate PostgreSQL store outside deployment migrations. Service-role RPCs use row locking and compare-and-set generations. Pending authorization and refresh operations have unique operation IDs. Revocation retains a generation tombstone and clears stored ciphertext. A stale callback or refresh cannot restore revoked credentials.
3. Permit only one claimant for an active refresh. Do not automatically steal or retry an uncertain refresh: the broker may already have rotated the old token. Require explicit new authorization after an unknown outcome. Keep sandbox and production isolated.
4. Test malformed data, context substitution, redaction, key removal/rotation, token expiry, privileges, stale writes, revoke races and concurrent refresh claims. Run isolated local SQL plus real PostgreSQL CI. Obtain independent review before integrating directly into main.

## Integration limits

The future authenticated gateway must derive ownership from a verified principal, reserve authorization before redirect, bind its generation/operation to the browser session, verify exact callback and browser binding, and keep app/vault/service secrets server-side. The existing session store and new token store are independent primitives; their association still needs integrated orchestration tests.

The cryptographic rewrap helper does not persist its result. A future storage operation needs its own compare-and-set protection against concurrent refresh/revocation. Retaining a pending refresh indefinitely is deliberately conservative; operational UI and recovery must ask for reauthorization rather than resubmitting an uncertain old refresh token.

Approved Connect signing, scopes, native redirect behavior, sandbox acceptance and the broker adapter remain external/integration work. No candidate schema or code in this slice changes the deployed relay or native clients. Local revocation does not assert remote Webull revocation or cancel an in-flight broker request.

## Verification

Record final local and CI results in the integration status document after tests and review. Physical and broker acceptance remain deferred or pending, not passed.
