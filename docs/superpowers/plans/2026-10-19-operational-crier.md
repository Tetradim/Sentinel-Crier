# Operational Crier implementation plan

**Goal:** Connect the existing monitor/publisher and native iPhone interface to
official Alpaca account data, confirmed customer orders, and durable Discord delivery.

**Architecture:** The iPhone app connects directly to Alpaca with device Keychain
credentials and explicit paper/live selection. The optional Python service monitors
broker fills while the phone is closed. Both use broker evidence and persistent
deduplication. Webull Connect remains dependent on the user's pending application.

**Tech stack:** SwiftUI, URLSession, Keychain, durable local storage; Python,
FastAPI, SQLite, httpx; GitHub-hosted macOS Xcode builds.

## Independently owned implementation work

- [ ] iOS: implement an Alpaca adapter, account configuration, real positions,
  stock/option tickets, fresh confirmation, persistent unknown-submission recovery,
  execution polling, Discord publishing and visible delivery state. Mock transport
  tests cover request fidelity, paper/live separation, duplicates and 429 recovery.
- [ ] Python: implement paginated authenticated Alpaca fill polling, initial
  baseline, restart recovery, account/environment separation and existing Store
  outbox integration. Add mocked broker tests and CLI/config selection.
- [ ] Release: replace obsolete ReplayKit instructions, document foreground iOS
  limits and optional always-on PC operation, fix simulator discovery, and provide
  a manually triggered signed archive workflow using repository secrets.
- [ ] Verify: run Python tests and syntax checks, compile/test iOS in macOS CI,
  inspect changes and fix failures, then record precisely which acceptance checks
  passed and which need Apple signing, a physical device or broker approval.

## Acceptance checks

No credentials in source, no automatic real-money tests, no inferred fills from
order acknowledgements, no blind resubmission after timeouts. Customer must see
the exact account/environment, contract, action, quantity and limit before confirming.
Discord can distinguish paper/live and preserve fill timestamps. Persisted evidence
must survive restart and must not leak between accounts. No unsupported promise of
continuous iOS background monitoring. No claim of App Store or Webull approval.

Run `python -m pytest -q`, `python -m compileall -q crier`, and
`node --check crier/static/app.js`. macOS CI generates the Xcode project, builds
the simulator target and runs TradingTests on an available iPhone simulator.
Signed distribution runs only with user-provided Apple signing secrets.
