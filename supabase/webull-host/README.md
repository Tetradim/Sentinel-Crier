# Webull host gateway candidate

`gateway.ts` exposes customer-authenticated `/v1` routes for capabilities,
browser authorization initiation, connection state, exact-symbol positions,
source order submission, lookup and cancellation. `service.ts` composes remote
Supabase Auth verification and service-role PostgREST ledger calls. The default
provider is unavailable.

`application.ts` and `functions/crier-webull-host/index.ts` now provide deployable
assembly. `authorization.ts`, `custody.ts` and `browser_store.sql` compose browser
launch/callback, encrypted token custody/refresh, local revocation and durable
rolling-window request admission. Authorization availability remains separate
from trading availability. See [activation instructions](../../docs/webull-authorization-deployment.md).

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
the composed authorization runtime. A concrete account/order **Provider remains
unfinished**. The official signature and pinned Connect HTTPS transport are
implemented in `transport.ts`, but generic personal Trading API resource schemas
are not assumed to be Connect-compatible. The transport's resource-path
constraint must be checked against issued integration details before binding
resources. No guessed order endpoint, fake authorized account or synthetic
success is enabled.

The application strips only known deployment prefixes and verifies protected
native routes through Auth. Browser requests use single-use stored state and a
Secure/HttpOnly cookie. Operator provisioning, schema installation, registered
callbacks and real activation remain required. The included Edge entry point has
no trading adapter; an environment flag alone cannot enable orders.

`bounded_json.ts` bounds actual response bytes while reading into an owned buffer.
Token replies are limited to 64 KiB; resource replies to one MiB. Invalid UTF-8,
overflow, aborted reads and non-success responses are refused, and cleanup does
not await an untrusted stream cancellation promise. Resource calls combine caller
cancellation with a ten-second deadline. Mutation retries remain disabled.

Keep the service-role key, application signing/client secrets and vault keys
server-side. Mobile requests carry only a verified Crier customer session.
Native source environments are sandbox/production; the destination intent
environment for this route is always Alpaca paper.

## Offline checks

```powershell
npm exec --yes --package deno@2.9.6 -- deno test supabase/webull-host
npm exec --yes --package deno@2.9.6 -- deno lint supabase/webull-host
npm ci --prefix supabase/tests
node --test supabase/tests/webull-host-ledger.test.mjs supabase/tests/webull-host-browser.test.mjs supabase/tests/webull-host-authorization.test.mjs
python -m pytest tests/test_webull_host_receiver.py -q
```

Tests use synthetic provider/auth responses and intercepted Alpaca HTTP. SQL
tests execute the candidate schema in PGlite. They do not establish real
PostgreSQL concurrency by themselves; separate PostgreSQL CI now checks
simultaneous launches, admission and source reservation. Neither establishes
approved Webull compatibility, real sandbox execution or physical-device
behavior. See [route status](../../docs/webull-iphone-host.md).
