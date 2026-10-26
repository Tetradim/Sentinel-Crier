# Webull host gateway candidate

`gateway.ts` exposes customer-authenticated `/v1` routes for capabilities,
browser authorization initiation, connection state, exact-symbol positions,
source order submission, lookup and cancellation. `service.ts` composes remote
Supabase Auth verification and service-role PostgREST ledger calls. The default
provider is unavailable.

`ledger.sql` is a candidate private/RLS-enabled schema with service-role-only
RPCs. It is deliberately outside deployment migrations. Source client IDs are
reserved before dispatch, and a repeated POST cannot repeat a broker submission.
Optimistic revisions prevent stale receipts from overwriting newer evidence.
Cancellation claims remain blocked during dispatch; completed/expired attempts
can be rearmed only by fresh authoritative working-order evidence, followed by
an explicit cancel request.

## Provider boundary still required

An approved `Provider` implementation must bind the verified customer and source
environment to encrypted Connect token custody, discover the customer's
authorized account, resolve exact stock/OCC contracts, sign the approved Connect
resource requests, normalize responses, and enforce long-only sales. Stock
position snapshots alone cannot prevent concurrent sells from oversubscribing
holdings: use broker-enforced reduction or durable account-wide quantity
reservations. Options sales must be sell-to-close.

Existing `../webull-connect` coordinator/vault/RPC components provide
authorization groundwork. They are **not yet composed into a concrete
Provider**. The official signature and pinned Connect HTTPS transport are
implemented in `transport.ts`, but generic personal Trading API resource schemas
are not assumed to be Connect-compatible. The transport's resource-path
constraint must be checked against issued integration details before binding
resources. No guessed order endpoint, fake authorized account or synthetic
success is enabled.

The service factory expects the `/v1` path at the gateway root. A future Edge
entry point must strip its exact deployment prefix before passing the request to
the handler. It must also compose the official browser callback/cookie flow,
apply per-customer request limits within Webull's limits, provision protected
keys and register the approved callback. Those deployment/provider components
are not supplied by this module.

Keep the service-role key, application signing/client secrets and vault keys
server-side. Mobile requests carry only a verified Crier customer session.
Native source environments are sandbox/production; the destination intent
environment for this route is always Alpaca paper.

## Offline checks

```powershell
npm exec --yes --package deno@2.9.6 -- deno test supabase/webull-host
npm exec --yes --package deno@2.9.6 -- deno lint supabase/webull-host
npm ci --prefix supabase/tests
node --test supabase/tests/webull-host-ledger.test.mjs
python -m pytest tests/test_webull_host_receiver.py -q
```

Tests use synthetic provider/auth responses and intercepted Alpaca HTTP. SQL
tests execute the candidate schema in PGlite. They do not establish real
PostgreSQL concurrency, approved Webull compatibility, real sandbox execution or
physical-device behavior. See [route status](../../docs/webull-iphone-host.md).
