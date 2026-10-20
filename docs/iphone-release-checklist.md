# iPhone installation and release

Crier's native app connects directly to a personal Alpaca API account. It does not
require the Python service, and this version does not include a screen-broadcast
extension. Webull Connect remains pending approval and integration.

## Install on your test phone with a Mac

1. Enroll an Apple development team and register `com.tetradim.sentinelcrier`.
2. Enable App Groups and associate `group.com.tetradim.sentinelcrier` with that app.
   Configure Keychain Sharing to match `ios/SentinelCrier.entitlements`.
3. Install Xcode with a currently accepted iOS SDK and XcodeGen. Run
   `cd ios && xcodegen generate`, then open `SentinelCrier.xcodeproj`.
4. Choose the SentinelCrier application target, select your development team in
   Signing & Capabilities, and keep automatic signing enabled for local testing.
5. Connect/unlock your iPhone, trust the Mac, enable Developer Mode when requested,
   select the phone as the run destination, and build/run.
6. Begin in Paper with a paper-account API key and secret. Configure a private
   test Discord webhook in Connections. Do not use a production trading channel
   for paper alerts that downstream bots might interpret as live signals.

## Build a signed package from Windows using GitHub Actions

The repository contains the manually triggered **Signed iPhone package** workflow.
Use an Apple-issued certificate/private key and matching provisioning profile;
GitHub cannot manufacture a developer membership or approve an application.

Create a GitHub environment named `ios-signing`. Configure these environment secrets:

| Secret | Value |
| --- | --- |
| `APPLE_TEAM_ID` | Apple developer team identifier |
| `BUILD_CERTIFICATE_BASE64` | Base64 of exported signing certificate plus private key (.p12) |
| `P12_PASSWORD` | Password protecting that .p12 |
| `BUILD_PROVISION_PROFILE_BASE64` | Base64 of the matching .mobileprovision profile |
| `KEYCHAIN_PASSWORD` | Random temporary CI keychain password |

Then select Actions → Signed iPhone package → Run workflow on main. Choose the
method matching your profile: `debugging` (development), `release-testing` (ad hoc,
registered devices), or `app-store-connect` (distribution). Download its IPA
artifact after success. Development/ad-hoc packages only install on eligible
provisioned devices. An App Store Connect IPA is uploaded to App Store Connect,
then distributed using TestFlight after Apple's processing/review. It is not a
universally sideloadable package.

This workflow exports only; it never uploads or submits your app automatically.
An app icon, version/build identifiers, bundle identity and entitlements must pass
Apple validation. A fresh accepted build number is required on every upload.
The workflow uses its run number; adjust if your existing App Store build number
is already larger. Do not place signing secrets in source files or chat.

## Physical-device acceptance

- Connect paper credentials, restart, and reconnect using Keychain storage.
- Verify account identity, environment, balances and positions against Alpaca.
- Discover a standard option contract, compare symbol/expiration/strike, and
  review quantity and per-share premium. Standard options use a 100 multiplier.
- Submit only after explicit confirmation. Acceptance must not appear as a fill.
- Exercise paper buy/sell, partial execution, cancellation and rejected orders.
- Interrupt a submission; confirm saved client-ID reconciliation prevents a
  second POST, including after app termination/restart.
- Check broker fill timestamp, quantity, price and paper label in Discord.
- Simulate offline and rate-limited delivery; inspect uncertain sends manually.
- Switch paper/live and credentials; ensure evidence is isolated by account and
  environment. Do not place a real-money order merely as an installation check.
- Background/close the app. It must not claim continuous monitoring; reopen and
  verify catch-up without historical replay or duplicates.

For unattended monitoring while Crier is suspended, use the optional PC service.
Select one publisher for a given account/destination to avoid independent duplicate
alerts. Quotes, complex options, automatic exits and other broker integrations
must not be assumed available because a navigation tab exists.

## Official references

- [Apple device installation](https://help.apple.com/xcode/mac/current/en.lproj/dev5a825a1ca.html)
- [GitHub signing certificates](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications)
- [TestFlight](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/)
- [Apple SDK requirements](https://developer.apple.com/news/?id=ueeok6yw)

The workflow and this checklist are preparation, not proof of a signed or approved
release. Record device and broker validation results against the exact commit.
