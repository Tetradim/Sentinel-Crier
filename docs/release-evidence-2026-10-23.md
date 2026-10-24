# Phase 4 candidate release evidence

Version: 0.2.0, candidate. Physical tests were explicitly deferred by the owner. This is not a declaration that physical acceptance passed or that any app store approved the application.

## Produced artifacts

- Android signed APK and AAB, version code 2, source `43eb1f3`. APK/AAB signatures verified against the persistent project identity. Downloaded files independently match manifest SHA-256 hashes and certificate fingerprint. [Release CI](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40051006512).
- Windows per-user installer, portable ZIP, manifest and SHA256SUMS, source `ea0c85e`. Installer compiles after replacing an unsupported Inno file function with the Win32 exclusive-open API. All downloaded artifact/manifest hashes were checked. Publisher Authenticode is explicitly **unsigned**. [Release CI](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40051324298).
- iOS release configuration, profile preflight, certificate/private-key validation, monotonic build-number checks, signed artifact provenance and explicit TestFlight upload workflow are prepared. No IPA was produced because the owner does not have Apple Developer enrollment.

Local artifact locations:

```text
dist/android-release-0.2.0/apk/release/app-release.apk
dist/android-release-0.2.0/bundle/release/app-release.aab
dist/android-release-0.2.0/release-manifest.json
dist/windows-release-0.2.0/SentinelCrier-0.2.0-Windows-Setup.exe
dist/windows-release-0.2.0/SentinelCrier-0.2.0-Windows.zip
```

## Refreshed Windows candidate with reconciliation fix

The current Windows candidate is rebuilt from `0bc7d36bdefe831e816dfde060df861165246e37`, including rejection of malformed broker evidence. [Release CI](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40063687203) passed: 485 Python tests, one platform-specific skip, installer compilation and the packaged offline smoke check. The version remains candidate 0.2.0; use the manifest commit to distinguish this build from the earlier candidate.

Downloaded artifacts are retained separately:

```text
dist/windows-release-0.2.0-0bc7d36/SentinelCrier-0.2.0-Windows-Setup.exe
dist/windows-release-0.2.0-0bc7d36/SentinelCrier-0.2.0-Windows.zip
dist/windows-release-0.2.0-0bc7d36/SentinelCrier-0.2.0-Windows-manifest.json
dist/windows-release-0.2.0-0bc7d36/SentinelCrier-0.2.0-Windows-SHA256SUMS.txt
dist/windows-release-0.2.0-0bc7d36/local-offline-smoke.json
```

All three checksum entries, artifact byte lengths and manifest hashes were checked locally, as was the exact source commit. The downloaded portable executable passed a fresh local offline UI/DPAPI credential round-trip check with zero network calls. Authenticode inspection confirms the installer is not signed, matching its manifest. The installer itself was not installed; physical acceptance remains deferred. Earlier Android/iOS evidence below is unchanged by this PC-only rebuild.

## Initial candidate automated validation

- Backend release-tool coverage and application tests: 452 passed with one platform-specific skip on Linux CI; local suite passed 452 before the final added Keychain wildcard regression, and the focused 31 iOS/Windows release tests passed afterward.
- Native iOS simulator: 83 passed, zero failures. [CI evidence](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40050997724).
- Android release validation: unit tests and release compilation passed; the workflow proved packaging refuses missing signing credentials before building and verifying signed artifacts.
- Android signing-manifest parser: two tests passed locally.
- Review corrections: valid Apple Keychain prefix wildcard grants are accepted; profile installation occurs only after its validated UUID is available to the next workflow step.

## Remaining release requirements

October 24 update: the Android portable backup was created and its tablet copy verified through read-back hashes; unsigned iPhone Release hardware compilation and resource validation passed. See [current Phase 4 status](phase4-status.md). Actual Apple signing/distribution, owner policy/contact decisions and the separate-machine signing drill remain unverified.

- Apple Developer membership, actual Apple certificate/profile and distribution metadata (support contact, privacy URL, eligibility) before signing or TestFlight distribution.
- A real Windows publisher certificate if Authenticode trust is desired; no self-signed publisher trust is claimed.
- Preserve the owner-passphrase Android backup on separate storage and prove separate-machine private-key recovery/signing; use monotonically increasing version codes for future updates. Signing materials are outside the repository and protected GitHub environment secrets; no private keys or passwords are in these artifacts or source files.
- Physical/device/network acceptance remains deferred. Existing debug Android installations use a different signing identity; do not erase unresolved journals to bypass an incompatible-signature install error. See the Android release guide.

Phase 4's available packaging work is complete, but the overall phase remains partially blocked by Apple enrollment/distribution inputs. No Apple or Google store submission was made.
