# Remote Host / Receive implementation

Approved design: devices are on unrelated networks. Both make outbound HTTPS
connections to one persistent relay. No router changes, inbound port scanning or
per-trade approval exchange. Broker credentials remain on the trading device.

- [x] Add opt-in public host provisioning and authenticated, expiring, single-use
  receiver invitations. Each receiver gets its own revocable read credential.
  Persist rate limits, tokens as hashes, expiry and claim atomically. Preserve old
  manually configured pairing. Test replay, expiry, role separation and revocation.
- [x] Add Python connection client and Windows Host/Receive controls. Keep saved
  channel credentials before broker activation, reject accidental channel changes,
  reuse existing pairing on subsequent clicks, preserve separate trading enable.
- [x] Add matching iOS controls, invitation parsing, secure persistence and reconnect
  through the existing workspace. Bundle optional default relay URL; no fake address.
- [x] Add a dedicated broker-free relay entry point and one-time hosted deployment
  blueprint. One provider account/deployment remains necessary: none exists today.
  Supply service URL through a shared build resource or invite link.
- [x] Test Python, native iOS CI and packaged Windows executable; review, repair,
  document deployment/setup boundaries and push directly to main.

API contract: `POST /api/connect/host {name,environment}` returns
`{token,role:"host",environment}`; `POST /api/connect/invite` with host bearer returns
`{code,expires_at}`; `POST /api/connect/receive {code}` returns
`{token,role:"follower",environment}`. Client adds its validated HTTPS origin as `url`
to create the existing IntentPairing. Share text is `https://origin/connect#CODE`.
Code is 16 uppercase base32 characters (spaces/hyphens ignored), valid ten minutes,
one receiver per invite. Reusing a redeemed code fails; after response loss, host
generates another code. Never silently replace an existing pinned pairing.

Default origin resource: `crier/connection-service.json` with `{"url":""}` until
deployment. Bundle the same resource into Windows and iOS. Empty means show service
setup, not successful connection. An invitation URL supplies the origin to receivers.
