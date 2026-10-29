# Multiple Hosts and Brokerage Connections Implementation Plan

**Goal:** One Crier installation runs multiple explicit host/account routes with independent pairing, credentials, journals, pause state and health.

**Architecture:** Preserve the current single-route runtime as an isolated session. A persisted connection registry selects a route for editing without stopping other routes. Each session uses an immutable opaque route ID and its own private directory. Existing single-route data remains the legacy route; never copy or delete journals on migration. Fail closed on concurrent access to the same broker/account/environment until shared-account reservation and ownership coordination is verified. Do not present unsupported brokers as executable. Broker credentials remain in existing protected native storage. No automatic entry enabling or reconnect on restart.

**Tech Stack:** Python/Tk/SQLite, SwiftUI/Keychain, Kotlin/SQLite/Keystore; existing relay channels and canonical instructions.

- [x] Windows registry/session manager and routing UI; route-local connect, host/receive, status, settings and disconnect; global shutdown drains every route.
- [x] iOS multi-connection runtime and selection UI with independent secure storage, journal, cursors and task cancellation.
- [x] Android multi-connection runtime and selection UI with scoped vault/settings/journal and foreground lifecycle.
- [x] Test same event across accounts, account collision refusal, selection during work, pause/restart, unresolved history retention and migration.
- [x] Review implementation and run appropriate Python/native/CI checks; direct main commit/push.
- [ ] Follow-up: shared-account reservations, arbitrary cross-broker adapters and real device/broker acceptance. Keep explicit exclusions while these are unimplemented; do not call all D.1 complete.

The owner approved D.1 implementation on October 29. Initial safe routing supports the existing executable Alpaca adapter. Webull authentication is separately verified; it is not an executable Crier resource adapter. Tradier execution remains unimplemented. The full request remains in progress until native/runtime and adapter gaps are closed.

Accepted initial independent-account scope: [verification evidence](../../acceptance/2026-10-29/multiple-connections/README.md). Full D.1 shared-account/cross-broker scope remains unfinished.
