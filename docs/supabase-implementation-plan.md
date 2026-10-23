# Supabase Free cross-network testing

User-selected hosting direction: Supabase Free, October 23, 2026.

## Design

Use a single Supabase Edge Function named `crier` as the existing HTTP protocol gateway, with transactional PostgreSQL state in a private schema. Keep opaque per-channel host and per-device receiver credentials; customer account login is not added as an implicit requirement. Broker keys remain on executing devices. Supabase service-role credentials exist only inside the function environment.

Persist instructions, invitation consumption, receiver permissions, diagnostics and cursor state in PostgreSQL. Reconnect uses durable cursor reads. A short bounded long-poll remains compatible with all existing clients; Supabase Realtime is not required or advertised as implemented by this migration. Future Realtime wakeups must remain hints and re-read durable records, not replace the execution ledger.

Allow the exact gateway base path `/functions/v1/crier` in client endpoint validation; preserve ordinary HTTPS origins. Invitations retain that prefix. No arbitrary URL paths, query strings or embedded credentials are accepted.

## Implementation and verification

1. Private PostgreSQL migration and service-role-only RPC dispatch, matching existing protocol semantics. Lock channels before allocating cursors to maintain publication commit order. Test isolation, expiry, single-use invitations, environment binding, duplicate/revision conflicts and revocation.
2. Edge request gateway with bounded bodies, opaque-token authorization through the RPC, safe response/error headers and bounded receive waits. Test using mocked PostgreSQL requests.
3. Update Python, Windows, Android and iOS base-path and invitation validation with regression coverage.
4. Run the SQL against a local PostgreSQL-compatible validation runtime, Edge tests, backend tests and native builds. Record which tests require hosted Supabase.
5. Deploy migration/function to an owner-created Free project, verify health/auth/isolation and repeat real cross-network paper acceptance. This final step requires the actual project and authenticated deployment access; local tests alone do not establish a hosted endpoint.

## External requirements

The owner must create/sign in to a Supabase Free project and supply its public project reference. Deployment credentials must be provided through an authenticated CLI session or protected local environment, not source control or public client configuration. No paid upgrade is authorized. Check Free quotas and idle-project behavior in the project dashboard before shared customer testing.
