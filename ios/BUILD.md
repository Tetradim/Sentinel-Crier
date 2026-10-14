# Milestone 1: native iOS project scaffold

The iOS application and broadcast extension are declared in `project.yml`. The project is generated using [XcodeGen](https://github.com/yonaskolb/XcodeGen) rather than checked-in machine-specific Xcode settings.

## macOS build

1. Install current Xcode and XcodeGen (`brew install xcodegen`).
2. From `ios/`, run `xcodegen generate`.
3. Run `xcodebuild -project SentinelCrier.xcodeproj -scheme SentinelCrier -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build`.
4. For device deployment, configure an Apple development team and provisioning for both the app and broadcast extension, then build in Xcode.

The GitHub Actions workflow attempts a simulator build on macOS on each relevant change. A successful simulator build is **not** proof that cross-app screen broadcasting works on a physical iPhone.

## Milestone 1 scope

- Native SwiftUI app entry point and initial setup interface.
- ReplayKit system broadcast picker wired to a bundled broadcast upload extension.
- Extension sample buffer intake and local Vision OCR proof of concept.
- Declarative XcodeGen project and CI build workflow.

## Not yet implemented

- Actual backend authentication, API health check, Discord configuration or publishing from iOS.
- Brokerage-specific OCR parser, trade verification, or automatic alerts from screen capture.
- Physical device validation, App Store provisioning, or signed distributable build.

No separate ReplayKit or Vision installation is required on customers' phones. Users must explicitly start screen sharing.
