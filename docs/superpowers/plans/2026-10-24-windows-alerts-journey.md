# Phase F.1 — Windows alerts-only journey

**Goal:** Connect an Alpaca account and use the existing Discord publisher without creating a mirroring channel or configuring a relay.

**Scope:** First vertical slice of Phase F. Cross-platform staged onboarding remains open after this slice. Keep the native iOS/Android Phase E runtime unchanged while this Windows-only slice is verified.

## Implementation

- [ ] Add a read-only Alpaca fill client with no submit/cancel interface. Test actual HTTP method/path mapping with MockTransport; use the existing fill polling, baseline, cursor and outbox transaction logic.
- [ ] Add `DesktopSession.connect_alerts(environment, key, secret, allow_live=False)`. Discover/pin account and environment, keep alerts credentials encrypted separately from intent pairing/journals, start only the fill/publisher loop, and expose honest mode/status.
- [ ] Isolate alerts-only publisher scope by verified account/environment so another profile's destination or pending queue cannot be consumed accidentally. Retain all old records and reject silent changes to pinned credentials/account.
- [ ] Preserve disconnect/resource cleanup, no duplicate connected sessions, paused startup and existing intent/mirroring behavior. Trade/receiver methods require an actual intent device/connection.
- [ ] Add a Start Here / alerts-only route that verifies the broker before routing the customer to the existing Discord preview/test/enable actions. Reuse saved credentials deliberately; a purpose preference or saved key is not verified readiness. No automatic test message, enable, connect or live execution on startup.
- [ ] Add meaningful runtime and hidden-window UI regressions: GET-only/no relay, wrong account/environment, restart, fill enrollment/new-fill queue, profile isolation, incomplete setup, disconnect and mode switching.
- [ ] Run the complete Python suite and Windows packaging/acceptance CI. Review state handling independently before committing directly to main; update customer docs and scope evidence after verification.

Actual broker/Discord acceptance remains deferred. Tests use synthetic accounts, encrypted dummy credentials, mocked HTTP and temporary data folders. An alerts-only account does not create or execute trading instructions.
