# Crier for Android

Standalone Kotlin Android app (Android 8/API 26 or later). The phone sends Alpaca orders itself and communicates with the intent relay over HTTPS; it does not need a PC execution process. The relay server must remain reachable.

## Build and verification

Use JDK 17, Android SDK 35, and Gradle 8.11.1:

```sh
cd android
gradle :app:testDebugUnitTest :app:assembleDebug
```

`.github/workflows/android-build.yml` performs those tasks and uploads a debug APK and test reports. Debug APKs are for installation/testing; production signing and Play distribution are separate steps. No broker credentials are needed by tests or CI.

Local verification on 2026-10-23: production and unit-test Kotlin sources compile directly against Android SDK 35 with Kotlin 2.0.21. All 41 offline JUnit tests pass, including shared protocol fixtures, invitation parsing, profile migration, credential rotation, execution recovery and Discord delivery transitions. Direct compilation does not establish APK packaging or physical-device correctness. CI and installation remain separate gates. No brokerage orders or Discord messages were sent during development.

## Setup and operation

1. Choose **Paper · simulated funds** or **Live · real funds** from the account picker. **Host** creates a connection using the bundled Supabase testing service; **Receive** accepts a complete invitation link or a 16-character code. A custom service address is available under **Advanced · connection service**. Manual JSON and customer router changes are not required. The testing service is not an availability or latency guarantee.
2. Enter your own Alpaca key and secret and choose a pricing policy. Price policy and quantity/age limits stay visible; detailed values are under **Advanced · execution limits**. **Save and verify account** performs a read-only account request. Live trading and market pricing require explicit authorization. Credentials, Discord webhooks and pairing tokens use the Android Keystore encrypted vault and never go into the relay or diagnostic export. Backup remains disabled.
3. Hosts choose **Create and share receiver invitation**. Links expire after ten minutes and are single use. **Receivers · review and revoke** lists device identities and revokes future relay access; existing broker orders remain the receiver's responsibility.
4. **Enable execution / Follow / reconnect** first reconciles pending broker orders. **Pause new entries** skips entries/replacements received during the pause, while cancel/exit handling continues. An unknown broker outcome blocks that trade; it never authorizes another POST. **Unresolved orders and recovery status** shows pending identities, connection faults and quarantined malformed events.
5. Hosts enter stock or canonical OCC option symbols, quantity and source limit price, then **Enter**. Select a journaled trade for **Replace**, **Cancel**, or **Exit**. Replace specifies total desired quantity; cancel stops the unfilled remainder. Exit reconciles and cancels buys before selling the acquired quantity, capped by available holdings. Only active standard 100-share option contracts are supported.
6. **Stop workers for settings / recovery** waits until in-flight workers finish. Rotate keys with **Save and verify account**; the verified account and channel must match the current journal. For a different account, select **Save a different account in a separate journal**; Host/Receive automatically creates a separate connection journal. **Restore a saved connection / account journal** restores its credentials, cursor, pending orders and evidence. Switching does not close old orders; restore the old profile to manage them. Never clear app data while orders or trade ownership remain relevant.
7. Worker, foreground/background, pause, reconnect and authentication states appear under **Refresh journal status**. Android 15 may time out background data sync; timeout pauses entries and stops the service. Reopen and explicitly enable/reconnect to reconcile before new work. Foreground resume also restarts previously enabled workers after process interruption. No execution wakeup or all-day background guarantee is advertised.

## Discord alerts

Configure a webhook, select **Card** or **Plain text**, and choose visible fields. Template syntax is under **Advanced · message template**. Preview renders readable sample text; **Queue test message** sends an explicit TEST message. Intent, manual observation and broker reconciliation fill provenance always remains visible. Fill quantity is cumulative and fill price comes only from the identity-validated broker response; a missing average price displays `Unavailable`, never the intended limit.

The SQLite outbox atomically reserves dispatch before transmission and records a Discord message ID as delivery evidence. Rate limits defer subsequent deliveries; definitive destination errors are blocked for correction. A crash, lost acknowledgement or ambiguous server failure remains `uncertain` until inspection and explicit retry. Retry confirmation explains duplicate risk. Delivery counts/status remain visible after restart. Destination changes are blocked while messages remain pending, blocked or uncertain; deliver them or explicitly discard them first. Discard retains message and execution evidence. Templates suppress Discord mentions. Selecting a different connection also selects its independent alert queue.

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
