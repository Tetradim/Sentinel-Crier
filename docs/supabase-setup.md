# Supabase relay for cross-network testing

This backend replaces the always-on Crier relay with a Supabase Postgres database and one Edge Function. The desktop app continues to hold broker credentials and execute orders locally. Supabase stores relay identities, hashed device tokens, invitation digests, events, and diagnostic observations. It does not place broker orders.

The implementation uses **durable HTTP long polling**, not Supabase Realtime push. Each receiver GET waits up to 25 seconds (20 by default), checking Postgres about once a second. Each check authenticates the token again, so a revoked receiver stops receiving events. Database queries and function cold starts add latency. This is suitable for a small cross-network trial; it is not a promise of trading latency or availability.

## Create a separate Free project

Sign into your own [Supabase dashboard](https://supabase.com/dashboard) and create a **new project on the Free plan**. Choose a region near the participating devices and keep the generated database password in a password manager. Do not upgrade, enter payment information, or reuse a production database just to try this relay. If your account has reached its Free project allowance, resolve that in the dashboard before proceeding.

Check the current [pricing allowances](https://supabase.com/pricing), [billing documentation](https://supabase.com/docs/guides/platform/billing-on-supabase), and [Edge Function limits](https://supabase.com/docs/guides/functions/limits) before running a trial. Plan allowances and pause policies can change; the dashboard is the authority for the actual project. Long polls consume function invocations, database queries, and egress even when no events arrive. One continuously connected receiver starts roughly 4,320 twenty-second polls per day (about 129,600 in 30 days), plus up to approximately one database RPC per second while connected. Reconnects and errors increase this. Stop receiver services when testing ends and inspect usage regularly.

As checked on October 23, 2026, the [Free plan](https://supabase.com/pricing) lists two active projects, 500 MB of database storage per project, 5 GB egress, and 500,000 Edge Function invocations; inactive Free projects pause after one week. These are shared-plan/project allowances as described by Supabase, not dedicated capacity for each receiver. The [Free function runtime limit](https://supabase.com/docs/guides/functions/limits) is 150 seconds of wall time and 2 seconds of CPU per request; the gateway's waits are capped well below that. This transport does not use the separate Realtime message allowance.

## Apply the schema and function

Windows users can run the guided deployment from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/deploy_supabase.ps1 -ProjectRef YOUR_PROJECT_REF
```

It uses interactive CLI authentication/password prompts, applies migrations, deploys the function, and saves the public gateway address only after a successful readiness check. Use `-SkipLogin` with an existing authenticated CLI session and `-Python` to select your project Python environment. Run it only against the dedicated Crier test project. It does not change the Supabase plan or purchase resources.

Run these commands from the repository root with Node.js installed. The [Supabase CLI documentation](https://supabase.com/docs/guides/local-development/cli/getting-started) describes account login and project linking. These commands are instructions for the project owner; merely checking out this repository does not deploy anything.

```powershell
npx supabase login
npx supabase projects list
npx supabase link --project-ref YOUR_NEW_PROJECT_REF
npx supabase db push
npx supabase functions deploy crier
```

Use the reference shown in the new project's dashboard URL. The link command may ask for the project's database password. Run `db push` only against the new dedicated project: it applies repository migrations to that database. Review the CLI's migration list before proceeding.

Supabase [provides](https://supabase.com/docs/guides/functions/secrets#default-secrets) `SUPABASE_URL` and the legacy `SUPABASE_SERVICE_ROLE_KEY` to the deployed Edge Function. The function uses the service key only in its server-side request to the `crier_dispatch` RPC. Never put the service-role key, database password, or Supabase account access token in the app's service address, invitation, source files, browser code, build configuration, or screenshots. The native clients use only opaque Crier device tokens, and need no Supabase API key.

The checked-in `[functions.crier] verify_jwt = false` is intentional. Crier tokens are opaque device credentials rather than Supabase JWTs. The RPC validates them on every protected operation; disabling Supabase's JWT filter does **not** remove that validation. Table access and the RPC must remain inaccessible to the `anon` and `authenticated` database roles. Only the server's `service_role` can invoke the dispatcher. Supabase Auth accounts and sign-in are optional future work, and are not implemented here.

## Connect the two devices

Set the connection service address on each device to:

```text
https://YOUR_NEW_PROJECT_REF.supabase.co/functions/v1/crier
```

The `/functions/v1/crier` path is part of the address. On the first device, select the intended paper/live environment and choose Host. Share the resulting invitation privately with the second device, then paste it into Receive. Invitations expire after ten minutes and can be consumed once. A page at `/connect` simply tells the recipient to paste the full invitation into the app; the private code stays in the URL fragment and is not read by that page.

Public readiness can be checked without a token:

```powershell
Invoke-RestMethod https://YOUR_NEW_PROJECT_REF.supabase.co/functions/v1/crier/health
```

Expect `status: ok`, `pairing_enabled: true`, and `protocol: 1`. This checks the RPC/database connection as well as the Edge Function. A 503 means the relay is unavailable; inspect migration/deployment status and project health without copying secrets into logs.

For the initial trial, keep both devices in paper mode, connect from separate networks, confirm that a harmless event reaches the receiver, disconnect/reconnect the receiver to verify cursor replay, and revoke it on the host to confirm it can no longer poll. Verify diagnostic timestamps on both devices. Real order execution still requires the local service to be running and separately configured.

## Security and operating limits

- Request bodies are limited to 32 KiB while streaming, before JSON parsing. Invalid JSON returns a generic validation message; backend exceptions return a generic 503.
- Responses use `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, and a restrictive content security policy. No CORS origins are enabled: these endpoints are intended for native clients.
- The gateway does not trust arbitrary `X-Forwarded-For` headers. Until a platform-authenticated client-IP mechanism is configured and tested, all clients share the database's `global` rate-limit bucket. This conservatively limits host creation to five per hour across the project and invitation redemption to twenty per minute. Reuse an existing host instead of repeatedly pressing Host during testing.
- Source code deliberately logs no bearer tokens, invitation bodies, service keys, or raw database errors. Provider-managed logs may still contain request metadata; limit dashboard access and review the platform's logging controls.
- Free project availability, database capacity, event retention, function invocations, wall-clock limits, and egress are finite. This gateway does not implement a background Realtime subscription, a hosted broker worker, a paid-plan upgrade, or a production availability guarantee. Inspect database growth and remove the dedicated test project when it is no longer needed, after preserving any data you need.

## Local checks

The gateway tests use a mocked PostgREST boundary and require no project, keys, network service, or database:

```powershell
npx --yes --package deno@2.9.6 deno test supabase/functions/crier/gateway_test.ts
npx --yes --package deno@2.9.6 deno check supabase/functions/crier/index.ts
```

They cover route prefixes, token forwarding, missing/malformed credentials, streamed body limits, safe errors, database health, bounded durable polling, and revocation while polling. Database integration tests are separate; passing gateway tests does not establish that a real project was migrated or deployed successfully.
