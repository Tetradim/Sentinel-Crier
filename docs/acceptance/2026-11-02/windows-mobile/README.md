# Windows mobile-style workspace

The Windows 0.5.2 workspace follows the approved Crier mobile palette and account-first layout. Native Tk remains the runtime. Home, Markets, Trade, Positions and Orders are primary destinations; Account retains all setup, pairing, allocation, delivery, health, provider, support and update tools.

## Scope and evidence

- The selected route and PAPER/LIVE/OFFLINE state stay visible. Account identities are masked in the header.
- Home reports retained trade/order counts. Unavailable balances and chart feeds are explicitly unavailable.
- Tickets preserve their existing action callbacks, option default, frozen command behavior and authorization guards. Position/order tables scroll on both axes.
- Stop all disconnects all local routes. Regression cases cover account switching during shutdown, delayed pairing completion and an already queued reconnect continuation.
- Scaled-window regressions cover footer visibility, Stop width, health actions, ticket scrolling and table access.
- Actual isolated native screenshots use a fresh temporary profile with no brokerage credentials or notifications. They are real application views, not generated mockups.

[Home](screenshots/windows-home.png) · [Trade](screenshots/windows-trade.png)

The Windows update does not publish a new Android package. [Mobile 0.5.1 acceptance](../../2026-11-01/review-refactor/README.md) remains the prior published baseline. Physical-device/provider acceptance, Webull activation and Apple signing remain owner-deferred.

Local verification: **1,320 Python/Tk tests passed, one optional test skipped** in 208.28 seconds. The sole warning is an existing Starlette/httpx test-client deprecation. `git diff --check` passed. Independent theme/ticket/shell review found no remaining blocking issues after the Stop-race fixes. Hosted installer and publication receipts follow separately.
