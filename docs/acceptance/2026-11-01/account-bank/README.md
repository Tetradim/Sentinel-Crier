# Cross-platform account banks, recovery and 0.5.0 publication

Accepted November 1, 2026 for the implemented Alpaca/source scope. Physical/provider work is [explicitly deferred by the owner](../../../deferred/2026-10-31-owner-provider-acceptance.md), not silently passed.

## Delivered and verified

- Windows, iOS and Android: opt-in shared-account banks, durable host/trade IDs, unit/dollar/equity-percentage stock/option pools, one shared cash ledger, separate option-buying capacity, owned exits, retained unknown reservations, terminal retirement and permanent duplicate protection.
- Guided recovery: all original order evidence, including terminal/archived IDs; per-order failures, retained ownership and broker inventory comparison; explicit audited verified-flat repair with fresh funds and unchanged external baseline. No repair enables entries or silently discards uncertain orders. Native setup/repair gates concurrent starts and persists paused permission.
- iOS: dark workspace header, reachable connection/add/bank/stop controls, positions search, explicit order-ticket sections, option contract summary, adaptable chart controls and read-only manual-order recovery. Simulator screenshots below show an actual running disconnected paper workspace, not a design mockup or live trade.
- Independent source review found and drove fixes for setup races, local-no-post recovery poisoning, cash/equity/option-capacity admission, late-fill ownership, nested Android locks, lost deficit handling and repair pause/audit semantics.

Automated results: **1,291 Python/Tk tests passed, 1 skipped; 196 iOS native tests passed; 187 Android unit tests passed.** All final simulator/emulator/customer acceptance jobs passed. See [machine-readable verification](verification.json).

## Public distribution and integrity

[Crier 0.5.0 release](https://github.com/Tetradim/Sentinel-Crier/releases/tag/v0.5.0) contains:

- [Windows installer](https://github.com/Tetradim/Sentinel-Crier/releases/download/v0.5.0/SentinelCrier-0.5.0-Windows-Setup.exe), portable ZIP, checksums, build manifest, installer acceptance and Ed25519-signed update catalog.
- [Signed Android APK](https://github.com/Tetradim/Sentinel-Crier/releases/download/v0.5.0/app-release.apk), AAB and operator-signing/hash manifest.

Published downloads were rechecked against manifest sizes/SHA256. The public update catalog verified using the app's pinned public key, and the actual updater path for a 0.4.0 client detected 0.5.0. Windows install/upgrade/downgrade rejection/profile preservation passed on an ephemeral hosted Windows runner. This does not assert a customer's physical PC was tested. The Windows installer is Authenticode-unsigned; its update catalog is Ed25519-signed. Android's operator-provided APK/AAB signatures were verified by the release workflow.

Runtime source: `e6efcf3`; final header/UI capture source: `1939d79`; Windows release source: `13a7aac`. The later revisions change UI/docs, not Windows/Android execution code. Android's manifest records its exact `e6efcf3` build source. No private signing key or brokerage credential is part of this report.

Verification runs: [cross-platform runtime](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41231836203), [Android package](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41231839666), [Windows publication](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41281626819), [final installed-app UI acceptance](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41281738881).

## Actual simulator screenshots

[Home](screenshots/ios-home-disconnected.png) · [Positions](screenshots/ios-positions-disconnected.png) · [Recovery](screenshots/ios-recovery-disconnected.png) · [Markets](screenshots/ios-markets-disconnected.png)

Apple enrollment/signing/TestFlight, physical device/lifecycle/VoiceOver/broker-UI and real cross-network latency checks, and Webull/provider approval/activation are owner-deferred. Additional broker executors, cross-installation shared-account coordination, independent strategies and automatic market fallback remain separately scoped future work. This acceptance does not make any profit or equal-fill-price guarantee.
