# Host and Receive across different networks

The iPhone and Windows apps connect **outward** to one shared HTTPS service. There
are no customer router changes, exposed trading ports or Discord parsing. Each
receiver gets its own read-only channel credential; brokerage keys stay on-device.

## One-time operator deployment

There is **no hosted Sentinel service configured yet**. The repository includes a
Render Blueprint for a dedicated relay. It starts no brokerage or Discord workers.

[Deploy the connection service on Render](https://render.com/deploy?repo=https://github.com/Tetradim/Sentinel-Crier)

1. Sign in to your own Render account using the deployment link. Review the service
   and disk charges before confirming. This template uses a paid `starter` service
   with a persistent disk; no subscription or deployment was purchased by Codex.
2. Deploy the Blueprint. It installs the app, creates an owner secret, enables
   Host/Receive provisioning, attaches persistent storage, and starts the relay.
   Render supplies the public HTTPS address; a custom domain is not required.
3. Wait for `/health` at the assigned address to return `status: ok` and
   `pairing_enabled: true`. Preserve the disk and owner secret across upgrades.
4. Enter that HTTPS origin in the host app's service setting once. Receiver
   invitation links carry the origin, so recipients do not need to enter it.
5. For distributions with no customer service setting, run:

   ```powershell
   python scripts/configure_connection_service.py https://YOUR-ASSIGNED-HOST
   ```

   Rebuild/distribute Windows and iOS. Both bundle `crier/connection-service.json`.
   The resource contains only a public URL, never an owner or brokerage key.

The template does not auto-deploy on every source commit. Schedule manual upgrades;
keep the data disk. Run exactly **one process/worker** for the current SQLite and
long-poll implementation. Monitor disk usage and back up the journal. Public host
creation has a capacity cap and per-peer rate limits; configure trusted proxy
addresses deliberately if your reverse proxy forwards client IPs.

Render's [free-service documentation](https://render.com/docs/free) describes idle
spin-down and the lack of persistent disks on free web services. The template uses
an always-on tier plus [persistent storage](https://render.com/docs/disks) so a
redeploy does not erase pairings. See the [Blueprint specification](https://render.com/docs/blueprint-spec)
for operator settings. Self-hosting the same Python service with HTTPS is also
supported: set `CRIER_DATA_DIR`, `CRIER_ACCESS_TOKEN` (32+ random characters), and
`CRIER_PUBLIC_PAIRING_ENABLED=true`; run `python -m crier.connection_server`.

## Customer connection

1. Configure each device's own brokerage credentials once. Use paper accounts first.
2. On the device originating trades, press **Host**. Share its invitation privately.
3. On the receiver, paste that link and press **Receive**. The link works across
   states, cellular networks and unrelated home networks once the service is online.
4. Confirm the displayed account/environment and separately enable following.
   Connection setup does not itself authorize a new trade.
5. Repeat Invite/Receive for additional followers. One invite admits one receiver,
   expires after ten minutes, and cannot be reused. The host publishes once to the
   channel; each paired receiver receives independently.
6. On later sessions, press Host or Receive without entering a new invitation.
   Saved credentials are reused. Network interruptions reconnect automatically
   while the app runs; normal expiry and invalidation still apply to delayed entries.

The desktop Host button also generates a fresh invite. iOS has **Invite another
receiver**. Newly joined receivers begin at their join point, not at previous trades.
Paired devices cannot silently switch accounts/channels; preserve their journals.
If redemption succeeds but the reply is lost, request a new invite. If broker login
fails after pairing, the app preserves the pairing so login can be retried.

Keep iOS foregrounded and the PC awake. Internet/broker latency still exists. No
physical interstate paper trial has been performed by automated tests. Run the
[paper acceptance checks](intent-paper-acceptance.md). Android remains compatible
with the existing manual intent pairing; this change adds quick buttons to iOS and Windows.

## Operator receiver controls

The host credential authorizes `GET /api/connect/receivers` and
`POST /api/connect/receivers/{id}/revoke`. These do not reveal receiver tokens.
Revoking one receiver blocks future reads without affecting others. The owner can
revoke a full channel with the existing `/api/sync/revoke/{id}` endpoint. Revocation
does not cancel broker orders that already exist. The service must be trusted: it
can see trade instructions and pairing credentials when serving requests.
