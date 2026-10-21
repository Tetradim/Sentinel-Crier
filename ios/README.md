# Sentinel Crier iOS (work in progress)

This folder contains native Swift sources, **not yet an installable iOS application**.

## Build preparation
1. On a Mac with Xcode, create an iOS SwiftUI app target named SentinelCrier.
2. Add `SentinelCrierApp.swift` to the app target.
3. Add a **Broadcast Upload Extension** target, with bundle identifier `com.tetradim.sentinelcrier.BroadcastUpload`, and add `BroadcastUpload/SampleHandler.swift` to that target.
4. Match the app's `RPSystemBroadcastPickerView.preferredExtension` with the extension's actual bundle identifier.
5. Configure signing and run on a physical iPhone. Simulator testing is not sufficient for cross-app broadcast capture.
6. Obtain explicit customer consent before recording any brokerage screen.

## Current functionality
- SwiftUI setup screen and system broadcast picker.
- Broadcast extension receives video frames and performs throttled on-device Vision text recognition.
- **No recognized text is stored or transmitted. No automatic trade detection or Discord alert originates from screen capture yet.**
- The backend URL field is configuration-only and does not authenticate or connect yet.

## Required before customer testing
- Commit a reproducible Xcode project with deployment targets and extension configuration.
- Implement broker-specific confirmed-fill recognition and structured local evidence.
- Add authenticated, encrypted transport to the existing event intake.
- Add order identity correlation, confidence thresholds, and duplicate prevention across capture/API sources.
- Provide clear pause, disconnect, error, and capture-active indicators.
- Verify iOS background, capture permission, app-switching, and screen-lock behavior on device.
- Run security/privacy review and a documented end-to-end test using synthetic fills before live customer tests.

Apple frameworks are part of iOS and the app bundle; customers do not separately install ReplayKit or Vision. Screen capture requires a user action and cannot guarantee observation of fills that aren't visible.

## Submission-time intent mirroring

Paste the v1 HTTPS pairing JSON in Settings → Submission-time mirroring, then connect
this device's own Alpaca account in the matching environment. Pairing role is `host`
or `follower`; tokens are stored in Keychain and never contain broker keys.
The durable journal is pinned to the first account and channel to prevent replay
against a different account. New followers start paused. Save follower settings to
enable entries; cancel and exit remain active while paused.

Host buy confirmation creates an intent trade and starts local broker execution and
relay publishing independently. Use the tracked trade row to replace its target
quantity/limit, cancel its pending entry remainder, or exit owned fills. Cancel
permanently invalidates entry for that trade; exit is still available afterward.
Manual sells are disabled for paired hosts: exits must reference tracked trades.
The legacy fill mirror is disabled whenever an intent pairing is saved. Discord
fill delivery continues through the existing account fill journal.

Keep the app foregrounded and unlocked while following. iOS does not guarantee a
persistent background receiver. Reconnecting resumes the saved relay cursor and
reconciles saved deterministic broker client IDs. Unknown submissions and ambiguous
cancellations remain blocked until broker evidence resolves them; a missing order
is never permission to submit again. Preserve the journal for recovery.

`IntentTests.swift` covers wire validation, revision ordering/tombstones, durable
unknown state, and local price policies. Native compilation/testing requires the
macOS Xcode workflow; no trading endpoint needs to be exercised for these tests.
# Remote Host / Receive

The account settings include Host, Receive, and Invite another receiver. A private
invitation link configures a receiver without copying JSON or a separate service
address. Pairing is stored in Keychain before brokerage activation. Subsequent
button presses reuse the saved role/channel and broker credentials. A wrong
Paper/Live selection is rejected before the invitation is consumed.

An operator must first deploy the connection service; see
[remote setup](../docs/remote-connect-setup.md). The shared
`crier/connection-service.json` resource can supply its public origin in distributed
builds. No default service has been invented or deployed. Keep iOS foregrounded.
