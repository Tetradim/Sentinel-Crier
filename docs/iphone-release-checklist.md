# Sentinel Crier — iPhone release and verification gates

This document separates code-complete functionality from an installable, tested iOS build. It does **not** claim the current project passes Xcode or is installable today.

## What is implemented

- Five-tab dark-mode iPhone command center: Dashboard, Activity, Alerts, Connections, Settings.
- Secure server connection and dedicated screen-upload credential storage.
- User-authorized ReplayKit broadcast extension with on-device OCR.
- Conservative Webull screen candidate extraction and continuous-screen coalescing.
- Durable, bounded JSON observation queue and authenticated HTTPS submission.
- Backend observation quarantine; independent verified-fill intake and Discord outbox.
- Server-rendered synthetic preview for supported message formats.
- Tests for duplicate observations, separated upload/admin authentication, and no OCR-driven delivery.

## Required release gates (must pass before customer testing)

1. **Xcode build:** macOS CI builds the app and extension for a generic iOS Simulator without signing. Inspect the workflow result rather than assuming it passed.
2. **Unit tests:** recognition XCTest and backend pytest both pass; test the current code, not an earlier commit.
3. **Provisioning:** an Apple developer signing identity and provisioning profiles for the app and ReplayKit extension. Both need matching App Group and shared Keychain access groups.
4. **Signed device build:** distribute through TestFlight or a signed development installation. GitHub Actions simulator builds cannot be installed on a physical iPhone.
5. **App/extension handoff:** confirm saving upload credentials in the app makes them available to the broadcast extension on a real device.
6. **ReplayKit behavior:** user starts/stops sharing, switches into Webull, backgrounds the companion, and handles interruptions.
7. **Recognition validation:** use redacted genuine Webull option receipts and negative cases (preview, canceled, pending, partial, unrelated app). Do not use a live trading order merely to test the app.
8. **Transport validation:** verify HTTPS upload, no raw screenshot transmission, offline queue/recovery, idempotent replay, and disable-upload purge.
9. **Discord isolation:** confirm OCR observations appear as `pending_review` and **never** publish automatically; verified broker fills follow the separate authenticated intake.
10. **Operational validation:** restart backend, review outbox status, simulate Discord rate limits and uncertain delivery, and verify customer-facing status messages.

## Windows + physical iPhone path

The customer can continue using Windows for backend development and administration. Native iOS installation still requires an Apple-signed build produced by Xcode on macOS (local or cloud-hosted), or a TestFlight build submitted with appropriate Apple developer credentials. An unsigned simulator build cannot be sideloaded onto a physical iPhone. Do not request a customer's Apple ID, signing certificates or brokerage credentials in chat.

When a signed TestFlight or development build exists, use the following acceptance checklist on the iPhone:

- Launch, navigate all five tabs, verify readable small-screen layouts and VoiceOver labels.
- Connect to an HTTPS test backend; check credentials survive restart.
- Confirm incorrect tokens produce a clear error and do not appear in logs.
- Enable screen upload; explicitly start ReplayKit broadcasting.
- View a non-trade screen; verify no false fill.
- View a synthetic or redacted completed-trade fixture; verify an observation appears as pending review.
- Disable upload; verify queued evidence is erased and further uploads stop.
- Confirm no Discord message is sent from OCR alone.
- Exercise delivery through independently verified synthetic backend fill events using a **test-only** Discord webhook.
- Stop broadcasting, restart app, and verify status is not falsely labeled monitoring active.

## Safety and limitations

ReplayKit requires explicit user authorization and cannot silently read Webull screens. OCR has no independent execution ID and is not proof of a completed broker fill. Broker-verified automated alerting requires a validated account-event source; the Webull observer remains experimental. A production-ready bot cannot be claimed until those conditions and the release gates above are met.

## Local backend checks

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
python -m compileall -q crier
node --check crier/static/app.js
```

## macOS build checks

```sh
cd ios
xcodegen generate
xcodebuild -project SentinelCrier.xcodeproj -scheme SentinelCrier -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
xcodebuild -project SentinelCrier.xcodeproj -scheme RecognitionTests -destination 'platform=iOS Simulator,name=iPhone 16,OS=latest' CODE_SIGNING_ALLOWED=NO test
```

These are commands to run, **not** assertions that they have passed.
