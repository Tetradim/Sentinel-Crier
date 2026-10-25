# Phase F.1 — Windows alerts-only journey

**Goal:** Connect an Alpaca account and use the existing Discord publisher without creating a mirroring channel or configuring a relay.

**Scope:** First vertical slice of Phase F. Cross-platform staged onboarding remains open after this slice. Keep the native iOS/Android Phase E runtime unchanged while this Windows-only slice is verified.

## Implementation

- [x] Add a read-only Alpaca fill client with no submit/cancel interface. Test actual HTTP method/path mapping with MockTransport; use the existing fill polling, baseline, cursor and outbox transaction logic.
- [x] Add `DesktopSession.connect_alerts(environment, key, secret, allow_live=False)`. Discover/pin account and environment, keep alerts credentials encrypted separately from intent pairing/journals, start only the fill/publisher loop, and expose honest mode/status.
- [x] Isolate alerts-only publisher scope by verified account/environment so another profile's destination or pending queue cannot be consumed accidentally. Retain all old records and reject silent changes to pinned credentials/account.
- [x] Preserve disconnect/resource cleanup, no duplicate connected sessions, paused startup and existing intent/mirroring behavior. Trade/receiver methods require an actual intent device/connection.
- [x] Add a Start Here / alerts-only route that verifies the broker before routing the customer to the existing Discord preview/test/enable actions. Reuse saved credentials deliberately; a purpose preference or saved key is not verified readiness. No automatic test message, enable, connect or live execution on startup.
- [x] Add meaningful runtime and hidden-window UI regressions: GET-only/no relay, wrong account/environment, restart, fill enrollment/new-fill queue, profile isolation, incomplete setup, disconnect and mode switching.
- [x] Run the complete Python suite and Windows packaging/acceptance CI. Review state handling independently before committing directly to main; update customer docs and scope evidence after verification.

Actual broker/Discord acceptance remains deferred. Tests use synthetic accounts, encrypted dummy credentials, mocked HTTP and temporary data folders. An alerts-only account does not create or execute trading instructions.

## Verification

Implementation source: `70397e3b2f97d63ae35fba28fc35e730fdd5d4a9`. The complete local suite passed **576 tests** with unraisable exceptions treated as errors. The focused desktop/alerts/Discord sequence passed **52 tests**, including **13 hidden-window UI tests**. UI teardown explicitly collects Tk objects on their owning thread; this removes a finalizer warning and delay when async HTTP tests immediately follow UI tests. The remaining warning is the existing Starlette/httpx deprecation.

Independent review covered account/environment pins, cancellation and disconnect, publisher isolation, restart and first-destination enrollment. No remaining actionable findings were reported. First-destination enrollment is restricted to an unconfigured alerts profile whose entire outbox has never been attempted; prior delivery evidence or a lost configured secret prevents reassignment.

[Windows release CI 40144737872](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40144737872) passed on that source: **575 tests passed, one platform-specific skip**, portable packaging, an unsigned installer and install/upgrade/downgrade rejection/uninstall checks. The downloaded [installer evidence](../../acceptance/2026-10-24/windows-alerts-setup/installer-acceptance.json) verifies synthetic journal and DPAPI credential preservation. Upgrade acceptance uses the same application payload under an acceptance-only next patch version; it is not proof of future application migrations or a physical customer installation. No native iOS/Android code changed in this slice; Phase E retains their separate CI evidence.

At completion of F.1, Phase F remained open for mobile purpose selection, staged preview/test/enable readiness and cross-platform restart/resume acceptance. The subsequent [guided setup implementation](2026-10-24-guided-setup.md) completed that automated scope with separate source-bound evidence. This F.1 slice alone reused the existing Discord controls and did not implement the complete guided journey.
