# Crier for Android

Standalone Kotlin Android app (Android 8/API 26 or later). Choose Alerts, Trade / share, or Follow. Alerts reads Alpaca fill activities and publishes to Discord without a connection service, channel or order engine. Trade / Follow sends Alpaca orders on the phone and uses the HTTPS intent relay; those journeys require the relay to remain reachable. A PC execution process is not needed.

## Build and verification

Use JDK 17, Android SDK 35, and Gradle 8.11.1:

```sh
cd android
gradle :app:testDebugUnitTest :app:assembleDebug
```

`.github/workflows/android-build.yml` performs those tasks and uploads a debug APK and test reports. Debug APKs are for installation/testing; production signing and Play distribution are separate steps. No broker credentials are needed by tests or CI.

Phase E verification on October 24, source `5fe75d0`: production and unit-test Kotlin sources compiled directly against Android SDK 35 with Kotlin 2.0.21; all **47 offline JUnit tests** passed. This includes picker roundtrips and preservation of invalid saved values. [Android CI 40134983406](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40134983406) also passed Gradle unit tests and debug APK packaging. These checks do not establish physical-device acceptance or signed release distribution. No brokerage orders or Discord messages were sent by these tests.

## Alerts guided setup

Phase F verification: final source `032e2af` passed full Kotlin compilation and **68 offline JUnit tests** locally; [Android CI 40150273615](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40150273615) passed unit tests and packaged the debug APK. Physical lifecycle and real broker/Discord acceptance remain deferred.

1. Choose **Alerts**. Enter paper/live Alpaca credentials, Discord webhook, format and template. **Save and verify Alerts account** checks read access and discovers the account identity. Read-only Alerts does not require trading permission or live-order authorization.
2. **Preview synthetic Discord message** shows TEST provenance without sending. **Send one synthetic test** is optional; only a numeric Discord message ID proves delivery. Pending, blocked or uncertain acknowledgements remain visible as such. A successful test is never labelled as a broker fill or treated as permission to publish.
3. **Enable real broker-fill alerts in foreground** explicitly permits monitoring and publication. Initial enable establishes the current time as the baseline; older fills are not replayed. Reconnect uses the retained cursor and may deliver fills accumulated since that baseline. Leaving the screen, changing inputs or restarting clears session verification, preview, test evidence and enable permission. Verify, preview and explicitly enable again to resume. Already dispatched requests may finish after leaving; their delivery evidence is retained.
4. **Alerts readiness and delivery history** shows each outbox identity and acknowledgement. Inspect Discord before **Close inspected undelivered messages**. Closing suppresses retries while retaining evidence; there is no automatic retry of uncertain messages. Destination changes are blocked until pending/blocked/uncertain jobs for that account/environment are explicitly closed or delivered, even after using another account. The original destination remains attached to that scope until a safe change.

Alerts credentials and its durable JSON cursor/outbox use a separate Keystore alias and encrypted preferences from Trade / Follow. Account/environment scopes retain their cursor, deduplication and delivery history. Fill records use the actual incremental broker activity quantity and execution price, including fractional quantities. There is no order mutation interface in the Alerts reader. Pagination processes one validated page per polling pass; malformed or failed broker reads stop monitoring for explicit reconnect. Foreground polling is approximately every ten seconds, not a timing guarantee. There is no Alerts background service or always-on guarantee in this bounded journey.

Selecting a purpose changes navigation only. Existing Trade / Follow workers continue independently until explicitly stopped; Alerts displays a dedicated stop control and retained recovery evidence. Opening any journey does not start a connection or worker automatically. Trade / Follow uses its existing explicit Enable/reconnect action and retains its reconciliation and live/market authorization controls. A physical-device lifecycle/UI run and real broker/Discord acceptance are still required; offline tests make no real network calls.

## Trade / Follow setup and operation

1. Choose **Paper · simulated funds** or **Live · real funds** from the account picker. **Host** creates a connection using the bundled Supabase testing service; **Receive** accepts a complete invitation link or a 16-character code. A custom service address is available under **Advanced · connection service**. Manual JSON and customer router changes are not required. The testing service is not an availability or latency guarantee.
2. Enter your own Alpaca key and secret and choose a pricing policy. Price policy and quantity/age limits stay visible; detailed values are under **Advanced · execution limits**. **Save and verify account** performs a read-only account request. Live trading and market pricing require explicit authorization. Credentials, Discord webhooks and pairing tokens use the Android Keystore encrypted vault and never go into the relay or diagnostic export. Backup remains disabled.
3. Hosts choose **Create and share receiver invitation**. Links expire after ten minutes and are single use. **Receivers · review and revoke** lists device identities and revokes future relay access; existing broker orders remain the receiver's responsibility.
4. **Enable execution / Follow / reconnect** first reconciles pending broker orders. **Pause new entries** skips entries/replacements received during the pause, while cancel/exit handling continues. An unknown broker outcome blocks that trade; it never authorizes another POST. **Unresolved orders and recovery status** shows pending identities, connection faults and quarantined malformed events.
5. Hosts enter stock or canonical OCC option symbols, quantity and source limit price, then **Enter**. Select a journaled trade for **Replace**, **Cancel**, or **Exit**. Replace specifies total desired quantity; cancel stops the unfilled remainder. Exit reconciles and cancels buys before selling the acquired quantity, capped by available holdings. Only active standard 100-share option contracts are supported.
6. **Stop workers for settings / recovery** waits until in-flight workers finish. Rotate keys with **Save and verify account**; the verified account and channel must match the current journal. For a different account, select **Save a different account in a separate journal**; Host/Receive automatically creates a separate connection journal. **Restore a saved connection / account journal** restores its credentials, cursor, pending orders and evidence. Switching does not close old orders; restore the old profile to manage them. Never clear app data while orders or trade ownership remain relevant.
7. Worker, foreground/background, pause, reconnect and authentication states appear under **Refresh journal status**. Android 15 may time out background data sync; timeout pauses entries and stops the service. Reopen and explicitly enable/reconnect to reconcile before new work. Foreground resume keeps saved settings but requires explicit Enable/reconnect after interruption. No execution wakeup or all-day background guarantee is advertised.

## Trade / Follow Discord alerts

For the Trade / Follow journey, configure a webhook, select **Card** or **Plain text**, and choose visible fields. Template syntax is under **Advanced · message template**. Preview renders readable sample text; **Queue test message** sends an explicit TEST message. Intent, manual observation and broker reconciliation fill provenance always remains visible. Fill quantity is cumulative and fill price comes only from the identity-validated broker response; a missing average price displays `Unavailable`, never the intended limit.

The Trade / Follow SQLite outbox atomically reserves dispatch before transmission and records a Discord message ID as delivery evidence. Rate limits defer subsequent deliveries; definitive destination errors are blocked for correction. A crash, lost acknowledgement or ambiguous server failure remains `uncertain` until inspection and explicit retry. Retry confirmation explains duplicate risk. Delivery counts/status remain visible after restart. Destination changes are blocked while messages remain pending, blocked or uncertain; deliver them or explicitly discard them first. Discard retains message and execution evidence. Templates suppress Discord mentions. Selecting a different connection also selects its independent alert queue.

## Diagnostics

Open **Diagnostics Â· timeline, premiums and latency** to inspect the latest 200
events. The app captures Alpaca IEX stock quotes or explicit OPRA option quotes
asynchronously, and exchanges clock/quote observations through the relay.
Receiver reports compare matching event revisions and feeds, with clock uncertainty
shown beside estimated delivery time. Missing permissions, stale quotes and invalid
clock evidence are displayed as unavailable. Use **Share diagnostics** or **Save
diagnostics** for JSON/CSV. See [execution diagnostics](../docs/execution-diagnostics.md).

## Execution safeguards and limits

SQLite commits each event, newest sequence, permanent cancel/exit invalidation and receiver cursor before broker execution. Host outbox and broker work run independently; publishing never waits for fills. Queued invalidations are dispatched first, and obsolete or expired queued entries are skipped. Events received by followers are never republished.

Each mutation is recorded before transmission. Broker responses are bound to deterministic event-derived client IDs shared across platforms, symbol, side, requested quantity and monotonic cumulative fills. Ambiguous submissions are reconciled by client ID; a 404 never causes a blind resubmission. An unresolved submission or cancellation deliberately blocks the trade and needs broker inspection. Cancellation is not considered complete until a terminal broker snapshot is received. Before an order POST, the adapter rechecks the latest desired revision after broker preflight. An exit limited by current available holdings continues its remaining requested quantity only after the preceding sell fills; canceled or rejected exits stop for inspection. The app never intentionally opens a short position and cannot sell more than this trade bought, less its completed sales.

Limit and bounded-limit orders can remain unfilled; bounded prices do not guarantee execution. `market` explicitly removes the limit. The executor supports whole quantities up to 1000. Device/offline lifecycle, broker integration, relay pairing and release signing still require actual device/paper-account acceptance testing before live use.

## Customer provider connections (source integration)

Open **Customer sign in · provider connections**, check availability, and sign in to your Crier customer account. Sign in and provider buttons remain disabled until the separate service advertises matching capabilities. Its default address is the bundled relay project's sibling `/functions/v1/crier-oauth`; only an exact HTTPS 20-letter Supabase project base is accepted. An undeployed or incomplete service keeps this path unavailable. Existing API-key and manual webhook setup remains usable.

Select paper/live and the setup journey before opening Alpaca or Discord consent in the browser. The browser signs in as the same Crier customer; brokerage passwords are never requested. Android registers `sentinelcrier://oauth/complete?flow=...` with `singleTop` and validates the raw URI in both installed return entry points. Customer access/refresh tokens use the separate Android Keystore encrypted `customer-session` namespace and key. Proofs, pending context and redeemed grants are process memory only: rotation can retain an authorization, process death requires starting again. Refresh is explicit. Ambiguous redemption is never retried.

Returning consent requires **Install returned provider connection · keep stopped**. Stop workers first. Alpaca's GET account identity must match the grant and saved account/environment; use an explicit separate account journal to change account. Trade/Follow still requires Host or Receive, and OAuth never enables execution or publishing. Alerts still requires verification, preview and explicit foreground enable. Discord installation retains both Alerts JSON and Trade/Follow SQLite destination/outbox ownership checks. Bearer requests never include API-key headers. API-key mode remains separate.

**Sign out** pauses entries, stops workers, waits for them to finish, clears process grants/proofs and forgets saved OAuth brokerage and Discord credentials before deleting the customer session. It preserves broker orders, profiles, cursors, unresolved messages and evidence. Logging in as another customer cannot reuse an earlier customer's Bearer connection. Logout does not cancel broker orders or revoke provider grants; inspect those with the provider separately.

Offline injected HTTP/JUnit checks cover login → begin → strict return → one-use redemption → broker identity installation, restart and logout, wrong identity/environment/owner, exclusive auth headers and ambiguous redemption. Source compilation does not establish installed-device browser interoperability, deployed service availability, provider registration or release acceptance. No real login, provider grant, message or order is exercised by these checks.

OAuth credential provenance includes the exact customer service URL and canonical customer UUID for both brokerage and Discord credentials. The same UUID on another Supabase project is a different identity. Restored connections, worker startup and direct Discord test/retry actions reject mismatched or missing OAuth provenance; manual API-key credentials keep their existing path. Login and logout require stopped workers, failed refresh preserves the previous customer fence, and inactive Activity returns wait in a process-owned inbox until foreground before consuming their one-use receipt.

## Connection health and recovery

Open **Connection health and recovery** below the journey buttons. The dialog shows
broker, fill-monitor, trade-sharing/receiving, execution-worker and Discord checks
for the selected journey. It refreshes local observations once a second while visible;
opening it or pressing Refresh view sends no network request. Idle is not proof of
remote connectivity. Saved successes remain history after restart and do not resume
monitoring, trading or publishing permission.

Alerts and Trade/Follow retain separate account/environment/connection scopes.
Stopped connection tickets reject late callbacks, and an old service cannot stop a
newer connection's health session. Alerts still stops when its screen leaves the
foreground; service status remains active until its owning workers drain. The health
history uses a coalesced background writer, with storage failures reported separately
from trading journals. No API key, webhook or pairing token is written into it.

Recovery actions show existing order/delivery evidence, return to setup, or explicitly
stop local workers. They never mark a broker order resolved or retry an uncertain
message automatically. Broker orders remain at the brokerage when local workers stop.
