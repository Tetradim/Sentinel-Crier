# Verification record — October 19, 2026 (America/Chicago)

Tested implementation: `b7b0dcc876142f4d15a47454bca4cd819a18144a`.
Subsequent documentation changes do not alter the tested application code.

| Check | Result |
| --- | --- |
| Windows Python suite | 206 passed; one dependency deprecation warning |
| Python 3.11 and 3.12 CI | Each 205 passed, one platform-specific skip |
| Python compileall and JavaScript syntax | Passed |
| iOS simulator build, Xcode 26.3 | Passed |
| Native XCTest | 35 tests passed, zero failures |
| Signed archive / physical iPhone | Not performed; signing assets and device required |
| Actual Alpaca/Discord requests in this finishing pass | None; mocked transports only |
| Webull Connect | Awaiting the user's existing application response |

CI evidence:
- [Simulator build](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39366357564)
- [Native tests and backend checks](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39366357599)
- [Python version matrix](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39366357575)

The initial native build-service crashes were reproduced on a clean retry.
Two Swift sources contained Windows-encoded bullet characters. A regression test
failed on those bytes, passed after UTF-8 repair, and the repaired native build
and tests then passed. The regression remains in the backend test suite.

## Remaining release gates and limitations

- Supply the Apple team/certificate/provisioning assets described in the
  [iPhone release checklist](iphone-release-checklist.md). The attempt to read
  the GitHub `ios-signing` environment returned 404; no signed workflow ran.
- Complete physical-iPhone paper execution and Discord acceptance tests before
  customer live-money validation. Simulator tests do not certify that path.
- Webull and Tradier native adapters are not implemented. Webull approval alone
  will not activate an adapter or market-data subscription.
- Native live chart feeds and bid/ask quotes remain unconnected. The charting
  research is guidance, not a shipped data integration. Limit prices are entered
  manually. Complex options, automated exits and multi-broker execution remain
  outside this implemented Alpaca path.
- Native polling and posting run while Crier is active, with catch-up on reopen.
  The optional PC monitor is required for continuous monitoring while suspended.
- Unknown orders remain blocked until broker reconciliation finds the order;
  uncertain Discord deliveries require manual inspection and are not resent.

This is a verified implementation checkpoint, not App Store approval or a claim
that every requested broker and feature is complete.
