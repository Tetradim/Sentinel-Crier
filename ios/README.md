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
