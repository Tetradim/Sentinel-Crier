# Crier for Android

Standalone Kotlin Android app (Android 8/API 26 or later). The phone sends Alpaca orders itself and communicates with the intent relay over HTTPS; it does not need a PC execution process. The relay server must remain reachable.

## Build and verification

Use JDK 17, Android SDK 35, and Gradle 8.11.1:

```sh
cd android
gradle :app:testDebugUnitTest :app:assembleDebug
```

`.github/workflows/android-build.yml` performs those tasks and uploads a debug APK and test reports. Debug APKs are for installation/testing; production signing and Play distribution are separate steps. No broker credentials are needed by tests or CI.

Local verification on 2026-10-20: all production Kotlin sources compiled directly using Kotlin 2.1.20 against Android SDK 35, and all 13 offline JUnit tests passed. The local Gradle process could not establish its loopback connection, so direct compilation is not evidence of APK packaging. CI and device installation remain separate gates. No brokerage orders were placed during development.

## Setup and operation

1. Install the debug APK on a test phone. Obtain a relay pairing from the channel owner. Paste JSON containing `url`, `token`, `environment` (`paper` or `live`), and `role` (`host` or `follower`). The URL must use HTTPS; use the host publish token only on the host and the follower read token only on followers.
2. Enter your own Alpaca key and secret, choose local pricing and maximum entry age/quantity, then tap **Save and verify account**. This makes a read-only account request. Live accounts and market pricing require their explicit checkboxes. Broker credentials and pairing tokens are encrypted with an Android Keystore AES-GCM key and never sent to the relay; app backup is disabled.
3. Tap **Enable execution / Follow**. New received entries execute without per-trade prompts. **Pause new entries** permanently skips new entry/replacement events received during the pause; cancellation and exits continue.
4. Hosts enter stock or canonical OCC option symbols, quantity, and source limit price, then tap **Enter**. Copy/retain the generated trade UUID. Use the same UUID, symbol and asset for **Replace**, **Cancel**, or **Exit**. Replace expresses the new total desired entry quantity; Cancel cancels only the pending remainder. Exit cancels/reconciles the entry before selling the trade's owned quantity, capped by available holdings. Only active standard 100-share option contracts are supported.
5. Use **Refresh journal status** for pending intents and reconciliation errors. Android's persistent service notification returns to the app. The service keeps long polling while enabled. Android 15 limits background data-sync service time; OEM power management and force-stop can also interrupt execution. Reopen Crier to resume. Do not assume receipt while the app is stopped.

Account, environment, role and pairing identity are pinned to the journal. Settings/credentials cannot change while workers may be in flight. To update pricing or rotate credentials for the same account, force-stop Crier in Android settings, reopen, save, and enable again. Use a separate Android app installation/profile for a different channel/account; clearing app data destroys its order-ownership records and must not be used while trades are outstanding.

## Execution safeguards and limits

SQLite commits each event, newest sequence, permanent cancel/exit invalidation and receiver cursor before broker execution. Host outbox and broker work run independently; publishing never waits for fills. Queued invalidations are dispatched first, and obsolete or expired queued entries are skipped. Events received by followers are never republished.

Each mutation is recorded before transmission. Broker responses are bound to deterministic event-derived client IDs shared across platforms, symbol, side, requested quantity and monotonic cumulative fills. Ambiguous submissions are reconciled by client ID; a 404 never causes a blind resubmission. An unresolved submission or cancellation deliberately blocks the trade and needs broker inspection. Cancellation is not considered complete until a terminal broker snapshot is received. Before an order POST, the adapter rechecks the latest desired revision after broker preflight. An exit limited by current available holdings continues its remaining requested quantity only after the preceding sell fills; canceled or rejected exits stop for inspection. The app never intentionally opens a short position and cannot sell more than this trade bought, less its completed sales.

Limit and bounded-limit orders can remain unfilled; bounded prices do not guarantee execution. `market` explicitly removes the limit. The executor supports whole quantities up to 1000. Device/offline lifecycle, broker integration, relay pairing and release signing still require actual device/paper-account acceptance testing before live use.
