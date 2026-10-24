# iPhone installation and release

**Apple distribution: deferred by owner on October 24, 2026.** The owner has no Apple Developer account. No signed
IPA, TestFlight eligibility, Apple processing, or physical-device acceptance has
been established. Physical testing is explicitly deferred by the owner. CI
preparation and simulator results do not satisfy those gates. Phase 5 automated work is authorized to continue while these requirements are deferred. See
[release metadata](ios-release-metadata.md) for missing owner inputs.

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

The workflow exports by default. The optional `upload_testflight` dispatch flag
uploads an App Store Connect export for Apple's TestFlight processing only when
explicitly selected. It never submits an app for App Store review or automatically
distributes it to testers. Upload success does not establish beta eligibility.
For upload, also configure `APP_STORE_CONNECT_KEY_ID`,
`APP_STORE_CONNECT_ISSUER_ID`, and `APP_STORE_CONNECT_PRIVATE_KEY_BASE64` in the
`ios-signing` environment. The last secret is a base64-encoded `.p8` API private
key. Do not use account passwords. Temporary upload keys are cleaned up even on
failure; private material is never part of the artifact.
The project includes an opaque 1024px app icon, version/build identifiers and a
settings-storage privacy manifest. Bundle identity, entitlements and distribution
metadata still need Apple validation. Review [native data handling](native-data-handling.md)
when supplying your privacy policy and App Store privacy answers.
A fresh accepted build number is required on every upload.
Enter an explicit `build_number` and the highest previous uploaded number in
`previous_build_number` (use zero only if never uploaded). The workflow requires
the new number to exceed that value and meet `release.json`'s iOS floor. It does
not query Apple's upload history, so the owner must verify the previous value.
It never silently resets a previous uploaded build. Marketing version comes from
the shared root `release.json`; run `python scripts/ios-release-project.py` before
generating a local project when changing releases. Signed CI also validates the
version/build read back from the exported IPA.

The separate preflight reports missing secret names without printing their
values. Before installation it checks profile expiration, distribution type,
exact app identifier/team, shared Keychain and App Group permissions, certificate
expiration, and whether the certificate belongs to the profile. Xcode remains the
authority on signing validity. The artifact contains the signed IPA plus
`release-manifest.json`: SHA-256, commit, version/build, public connection endpoint,
profile identity/expiry and public certificate metadata. It contains no signing
key or separate decoded provisioning profile. Apple's exported application can
contain embedded provisioning material. Do not place signing secrets in source files or chat.

## Release archive validation without membership

The normal **iOS build** workflow also archives a Release build for generic iPhone
hardware with signing disabled, verifies arm64 support, and checks the archived
bundle identity/version, compiled icon/assets, privacy manifest and public relay
configuration. Its artifact is a JSON validation report, not an IPA or app to
install. This check can detect device Release build/resource problems before an
Apple membership exists; it does not validate signatures or distribution rights.

Prepared [support](release/support-draft.md), [privacy](release/privacy-policy-draft.md)
and [review-note](release/ios-review-notes-draft.md) drafts identify remaining owner
decisions. GitHub Issues is the approved support route. A published approved privacy
policy and its accessible in-app link remain required before distribution.

## Physical-device acceptance

Status: **deferred by owner; not passed**. Record actual device, iOS version,
commit, build, date and results when this work is authorized and possible.

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
