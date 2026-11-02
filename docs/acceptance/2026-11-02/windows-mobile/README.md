# Windows mobile-style workspace

The Windows 0.5.2 workspace follows the approved Crier mobile palette and account-first layout. Native Tk remains the runtime. Home, Markets, Trade, Positions and Orders are primary destinations; Account retains all setup, pairing, allocation, delivery, health, provider, support and update tools.

## Scope and evidence

- The selected route and PAPER/LIVE/OFFLINE state stay visible. Account identities are masked in the header.
- Home reports retained trade/order counts. Unavailable balances and chart feeds are explicitly unavailable.
- Tickets preserve their existing action callbacks, option default, frozen command behavior and authorization guards. Position/order tables scroll on both axes.
- Stop all disconnects all local routes. Regression cases cover account switching during shutdown, delayed pairing completion and an already queued reconnect continuation.
- Scaled-window regressions cover footer visibility, Stop width, health actions, ticket scrolling and table access.
- Actual isolated native screenshots use a fresh temporary profile with no brokerage credentials or notifications. They are real application views, not generated mockups.

[Home](screenshots/windows-home.png) · [Markets](screenshots/windows-markets.png) · [Trade](screenshots/windows-trade.png) · [Trade management](screenshots/windows-trade-management.png) · [Positions](screenshots/windows-positions.png) · [Orders](screenshots/windows-orders.png) · [Account](screenshots/windows-account.png)

The Windows update does not publish a new Android package. [Mobile 0.5.1 acceptance](../../2026-11-01/review-refactor/README.md) remains the prior published baseline. Physical-device/provider acceptance, Webull activation and Apple signing remain owner-deferred.

Local verification: **1,320 Python/Tk tests passed, one optional test skipped** in 208.28 seconds. The sole warning is an existing Starlette/httpx test-client deprecation. `git diff --check` passed. Independent theme/ticket/shell review found no remaining blocking issues after the Stop-race fixes.

## Published Windows 0.5.2

Source: `ca10f9c277853e0ae83cbe6ac18186f02f70d4af`.

[Installer and portable ZIP](https://github.com/Tetradim/Sentinel-Crier/releases/tag/v0.5.2) · [Structured verification](verification.json) · [Installer evidence](installer-acceptance.json).

- [Windows release and publication](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41439789533): passed; full Python/Tk suite, packaging, installer acceptance and update signing.
- [Windows portable build](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41439779489): 1,320 tests passed, one skipped; packaged-app smoke test passed.
- [Customer acceptance](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41439779532): Windows journeys, Android emulator and two iOS UI tests passed.
- [Trading safety](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41439779518): backend and 199 native iOS tests passed.
- [Android build/unit tests](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41439779409), [iOS build](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41439779871), [backend](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41439779576) and [provider preparation](https://github.com/Tetradim/Sentinel-Crier/actions/runs/41439779353): passed.

The public installer and ZIP hashes/sizes match their release manifest. The public update catalog verifies against the bundled Ed25519 trust key. The actual 0.5.1 updater discovers 0.5.2, downloads it and verifies the staged installer. No installer was executed on the owner's PC.

Installer acceptance runs on an ephemeral hosted runner: fresh install, acceptance-only next-patch upgrade, downgrade rejection, DPAPI/journal retention and uninstall preservation. This is not physical customer-machine acceptance or proof of future application migrations. The installer remains Authenticode-unsigned; the update catalog is signed.
