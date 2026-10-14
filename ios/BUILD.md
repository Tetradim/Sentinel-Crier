# Sentinel Crier iOS companion: build and testing

The SwiftUI app, ReplayKit extension and recognition test target are declared in `project.yml` and generated using XcodeGen.

## Build on macOS or GitHub Actions

1. Install Xcode and XcodeGen (`brew install xcodegen`).
2. Run `cd ios && xcodegen generate`.
3. Run `xcodebuild -project SentinelCrier.xcodeproj -scheme SentinelCrier -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build`.
4. Run `xcodebuild -project SentinelCrier.xcodeproj -scheme RecognitionTests -destination 'platform=iOS Simulator,name=iPhone 16,OS=latest' CODE_SIGNING_ALLOWED=NO test`. Adjust the simulator destination to an installed runtime.
5. For device installation, configure an Apple development team and provisioning for the app and broadcast extension. Both targets need App Group `group.com.tetradim.sentinelcrier` and Keychain Sharing `<TeamPrefix>com.tetradim.sentinelcrier.shared`. The main app additionally requires its app-only Keychain group.

The repository's macOS CI workflow attempts to build and run tests. A configured workflow is not evidence of a passing run; inspect GitHub Actions results.

## Implemented stage-one code

- Native SwiftUI setup and HTTPS backend status check; main admin token in device Keychain.
- Explicit ReplayKit system broadcast picker and broadcast extension lifecycle.
- On-device Vision OCR with a conservative Webull options parser.
- Frame-state coalescing so one continuously visible receipt is not repeatedly enqueued.
- Independent screen-upload Keychain credential, App Group endpoint configuration, local bounded queue, and HTTPS upload retries.
- Backend `POST /api/screen-observations` authenticated with `CRIER_SCREEN_UPLOAD_KEY`, storing observations as `pending_review`.
- No OCR-driven Discord publishing or order placement.

## Known limits / validation gates

- The iOS app and extension have **not** been verified on a physical iPhone.
- ReplayKit cannot run invisibly in the background and must be started by the user.
- Upload retries require a subsequent active broadcast; a stopped extension does not drain its queue.
- Webull OCR patterns require real redacted completed, pending and partial-order examples.
- Identical screen fields are not unique execution IDs; independent broker verification is needed for unattended Discord alerts.
- Provisioning, Keychain sharing, build, XCTest and on-device HTTPS uploads need to be checked before customer installation.

See [screen upload deployment guide](../docs/webull-screen-upload.md).
