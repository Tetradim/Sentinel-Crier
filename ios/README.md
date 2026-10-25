# Sentinel Crier iOS

The native SwiftUI application and test target are generated from `project.yml`
with XcodeGen. Build and test using the repository's macOS iOS workflows. Signed
installation and physical iPhone acceptance remain external requirements.

## Guided setup

Open **Home**, choose **Alerts only**, **Trade / share** or **Follow trades**, then
connect the selected paper/live Alpaca account. Saved Keychain credentials can be
reused by leaving the key fields empty. Restart never connects automatically.
Changing purpose or environment requires an explicit disconnect and retains the
account-scoped fill/order journal and pinned intent/channel recovery evidence.

Alerts only verifies read access and monitors native Alpaca FILL activities without
requiring a mirroring channel or activating intent/legacy mirroring workers. A
trading-blocked account can still verify read access. Existing pinned channel
account/environment protections still apply when rotating shared credentials.
Trade and Follow retain their existing reconciliation and explicit live-order
confirmation requirements; paper practice and synthetic Discord tests are optional.

Save a Discord webhook in Connections. In Alerts, save the desired format, select
**Preview current destination**, optionally **Send synthetic test message**, and
explicitly turn on **Publish verified broker fills**. The test is labeled sample
data and its acknowledgement is separate from broker-fill evidence. Unconfirmed
tests may have arrived: inspect Discord before retrying. A saved webhook or format
is configuration, not proof of a network connection or permission to publish.
Account verification, preview, test results and delivery permission are session
state; disconnect, restart, suspension or relevant edits invalidate readiness.
Keep the app open and unlocked. Returning from suspension reconciles the connected
account, but requires a new preview and explicit delivery enable. Restart requires
explicit reconnect. A rapid return while a request is still pending discards the
old response; the next foreground refresh reconciles before restoring readiness. Earlier fills are not replayed on first connection; durable
baselines/outboxes retain the existing uncertainty and duplicate protections.
Deliver or close outstanding alerts before changing a saved destination.

`GuidedSetupTests.swift` covers simulated read-only setup, trading-blocked read
access, restart, readiness invalidation, failed/unconfirmed tests and stale async
acknowledgements. These checks use synthetic credentials and injected URL sessions.
No real broker orders or Discord messages are part of automated acceptance.

Phase F source `d1eb60d` passed [94 native tests](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40149692050), including 11 guided setup cases, and [simulator/unsigned hardware archive checks](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40149688984). These checks do not provide signing, an installable iPhone package or physical acceptance.

## Submission-time intent mirroring

Paste the v1 HTTPS pairing JSON in Settings → Submission-time mirroring, then connect
this device's own Alpaca account in the matching environment. Pairing role is `host`
or `follower`; tokens are stored in Keychain and never contain broker keys.
The durable journal is pinned to the first account and channel to prevent replay
against a different account. New followers start paused. Save follower settings to
enable entries; cancel and exit remain active while paused.

Host buy confirmation creates an intent trade and starts local broker execution and
relay publishing independently. Use the tracked trade row to replace its target
quantity/limit, cancel its pending entry remainder, or exit owned fills. Cancel
permanently invalidates entry for that trade; exit is still available afterward.
Manual sells are disabled for paired hosts: exits must reference tracked trades.
The legacy fill mirror is disabled whenever an intent pairing is saved. Discord
fill delivery continues through the existing account fill journal.

Keep the app foregrounded and unlocked while following. iOS does not guarantee a
persistent background receiver. Reconnecting resumes the saved relay cursor and
reconciles saved deterministic broker client IDs. Unknown submissions and ambiguous
cancellations remain blocked until broker evidence resolves them; a missing order
is never permission to submit again. Preserve the journal for recovery.

`IntentTests.swift` covers wire validation, revision ordering/tombstones, durable
unknown state, and local price policies. Native compilation/testing requires the
macOS Xcode workflow; no trading endpoint needs to be exercised for these tests.
# Remote Host / Receive

The account settings include Host, Receive, and Invite another receiver. A private
invitation link configures a receiver without copying JSON or a separate service
address. Pairing is stored in Keychain before brokerage activation. Subsequent
button presses reuse the saved role/channel and broker credentials. A wrong
Paper/Live selection is rejected before the invitation is consumed.

An operator must first deploy the connection service; see
[remote setup](../docs/remote-connect-setup.md). The shared
`crier/connection-service.json` resource can supply its public origin in distributed
builds. No default service has been invented or deployed. Keep iOS foregrounded.

### Intent execution diagnostics

Open **Execution diagnostics** on a tracked intent trade to see each revision's
journal/arrival, relay acceptance, order dispatch, broker response and reconciled
status/fill evidence. JSON and CSV sharing creates files containing the exact event
and authorized local/remote observations; account credentials are never included.
Existing journals without diagnostics remain readable.

Quotes are asynchronous near-event snapshots, not exact button-time prices or
fills. Stock capture explicitly requests Alpaca IEX; option capture explicitly
requests OPRA and does not fall back to indicative data. Missing permissions,
failed capture, stale quotes, and unavailable clocks remain visible as unavailable.
Premium comparisons use ask for entry/replace and bid for exit, matching event and
feed, quotes within five seconds of the corrected event time, and quotes fresh at
capture completion. Broker cumulative fill/average-price evidence is shown separately.

Delivery latency uses independent midpoint relay clock samples, monotonic RTT,
and summed uncertainty. Samples expire after 60 seconds; wall-clock jumps invalidate
them. The receiver can compare the host and its own observation. The host cannot
see receiver observations. A first event before clock calibration has unavailable
latency. Diagnostics never await quotes before dispatching orders. Quote requests
are capped at eight concurrently; observation upload retries stop after six tries,
remote fetches after twelve, with at most twenty records processed per pass.
Restarted incomplete captures are marked unavailable rather than recreated later.

### Customer and provider sign-in (G6b source integration)

Home → Provider connections checks the dedicated `crier-oauth` service before
showing customer sign-in and provider consent actions. Its default base is the
bundled relay project's sibling `/functions/v1/crier-oauth`; Advanced accepts only
an exact `https://<20 lowercase letters>.supabase.co/functions/v1/crier-oauth`
base. Missing deployment/configuration leaves OAuth unavailable. Existing API-key
and manually saved Discord webhook setup remain available.

Crier customer passwords are distinct from brokerage passwords. Customer sessions
use device-only Keychain storage and are pinned to the configured OAuth service.
Refresh is an explicit, single-attempt operation that first stops the connected
workspace. An uncertain rotated refresh requires signing in again; a separate
Keychain owner/service binding remains until explicit logout, preventing an account
switch from reusing earlier credentials. Official browser consent independently requires the
same Crier customer. The app registers `sentinelcrier://oauth/complete?flow=...`;
its strict return matcher requires a live in-memory owner/provider/environment/
purpose record and device proof. Returns wait until the app is active before
consuming that pending record; status/redemption responses are retained across
scene changes without retry. Restarting discards that proof. Return links
contain no customer or provider credentials. A failed or lost redemption is never
automatically retried; authorize again.

After consent, **Verify and save credential** requires a disconnected workspace.
Alpaca installation performs only a GET to the selected paper/live account and
checks redeemed identity plus saved intent pins before Keychain storage. Broker
requests use either OAuth Bearer or API-key headers, never both. OAuth credential
records retain both customer UUID and exact service URL; a matching UUID in another
Supabase project cannot unlock them, and old OAuth records missing provenance
require reauthorization. Legacy API-key records remain readable. Discord installation
uses the manual destination safeguard and rejects changes while delivery entries
are unresolved; preview and publishing permission are invalidated. Consent never
connects workers, places an order, activates a channel, sends a test or enables
publishing. Reconnect and review permission explicitly. Sign-out invalidates shared dispatch permits and stops workers
before removing OAuth credentials and retains order/delivery journals; credentials
owned by another Crier customer cannot be reused. API-key credentials remain.

`ProviderConnectionsTests` uses an injected URLProtocol session, temporary Keychain
service and temporary journals to exercise login → begin → installed return →
one-use redemption → verified explicit install, plus strict service and auth-header
boundaries. Run the iOS test target in macOS CI. This Windows workspace has no
Xcode; signing, real provider registration/deployment and physical consent/browser
return acceptance remain required separately. No real provider grant, message or
order was exercised here.

## Connection health

Open **Home → Connection health and recovery**. The view displays actual broker,
fill, relay, execution-worker and Discord observations, their last successful checks,
and recovery navigation. Refresh view updates local presentation only. It does not
send a broker/Discord/relay request or grant execution/delivery permission.

Health evidence is scoped to the verified account/environment, journey, OAuth customer provenance where applicable,
pairing and destination. A new connection or foreground resume requires fresh checks;
late callbacks from a stopped session cannot restore health. Saved timestamps survive
restart while readiness does not. Clock discontinuity and stale observations are shown
separately. The view links to existing account setup, orders and delivery history; it
cannot manually resolve an unknown order or automatically retry an uncertain message.

Native preference storage holds diagnostic timestamps and fixed reason codes, with
credential-bearing identities hashed before storage. Health is informational and is
separate from the authoritative order/delivery journals. Keep the app foregrounded:
returning reconciles a connected account, restart requires reconnect, and Discord
publishing must be explicitly re-enabled after suspension.
