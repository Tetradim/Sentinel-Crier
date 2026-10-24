# Phase 4 status - October 24, 2026

Phase 4 implementation work is closed with explicit owner-authorized deferrals as of October 24, 2026. The owner instructed continuation into Phase 5 while deferring Apple enrollment/signing and every Phase 4 item that cannot be completed autonomously. This is a workflow handoff, not a claim that distribution or acceptance requirements passed. No signed iPhone package or store approval is claimed.

| Requirement | Evidence / remaining action |
| --- | --- |
| Windows installer and portable package | Produced from `0bc7d36`; downloaded hashes and local offline UI/DPAPI smoke test passed. Publisher signing remains optional and absent. See [candidate evidence](release-evidence-2026-10-23.md). |
| Android signed APK/AAB | Produced with the persistent project identity; version code 2. Signature/fingerprint and downloaded checksums verified. |
| Android portable key backup | Created through an owner-entered masked passphrase, re-encrypted as PKCS12; original identity and CI credentials unchanged. Copied to the owner's Galaxy Tab; all four files copied back and SHA-256 matched. No passphrase saved in backup files or source. |
| Backup recovery drill | Synthetic re-export/reopen tests pass. Real separate-machine private-key recovery and disposable signing drill remain outstanding. The tablet must be disconnected for offline custody; disconnection was requested, not independently observed. |
| iPhone simulator and Release hardware compilation | [CI 40065332880](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40065332880) passed the simulator build and unsigned `iphoneos` Release archive, arm64 verification, bundle identity/version, compiled assets/icon, privacy declaration and bundled relay configuration checks. |
| Actual iPhone signing and TestFlight | Workflow prepared; blocked by absent Apple Developer enrollment/team, Apple-issued certificate/profile and App Store Connect inputs. Unsigned validation is not an installable IPA. |
| Support | Owner approved public GitHub Issues. [Support draft](release/support-draft.md) is prepared; actual distributor/contact details and private request route still need owner input. |
| Privacy and review metadata | [Privacy draft](release/privacy-policy-draft.md), [App Review notes](release/ios-review-notes-draft.md) and [metadata worksheet](ios-release-metadata.md) are prepared. Distributor identity, retention/deletion commitments, actual contacts and approved public privacy URL are unresolved. Native in-app policy link must be added once that URL is approved. |
| Apple eligibility | Financial-app distribution eligibility/permissions and regions must be resolved with Apple. Enrollment or a successful compile does not establish eligibility. |
| Upgrade and physical acceptance | Journal migration/recovery and packaging checks have automated coverage. Actual install/update, signing-key recovery on another machine and cross-device/paper acceptance are not established by those checks. Physical trials remain deferred under the owner's instruction. |

## Retained evidence

- Complete local Python suite: **516 passed**, including 18 signing-backup safety/GUI/synthetic-key tests and 12 archive-resource tests. One existing FastAPI/Starlette HTTPX deprecation warning remains. Final independent review found no actionable regressions.
- Device archive report: `dist/ios-release-archive-5c4a874/ios-unsigned-archive-validation.json`. It explicitly records `signing: not_verified`, `installable_package: false` and deferred physical acceptance.
- Tablet backup location: `Galaxy Tab A9+ 5G / Internal storage / Documents / SentinelCrier-SigningBackup-20261024-2c710b33`.
- Backup contents: encrypted `android-release-backup.p12`, public `manifest.json`, `SHA256SUMS.txt` and `RESTORE.txt`. The public certificate fingerprint matches the identity recorded in [Android release instructions](android-release.md).
- Private staging and read-back copies remain outside the repository under the current Windows user's owner-only `%LOCALAPPDATA%/SentinelCrier/SigningBackups/` folder. No signing keys, passwords or private backup artifacts were committed or attached to releases.

## Deferred owner/external steps

These are deferred under the owner's latest instruction. They do not block automated Phase 5 work, but still must be satisfied before the corresponding release/distribution claims.

1. Preserve the backup passphrase separately and keep the tablet copy offline. Complete `RESTORE.txt` on another trusted machine before relying on that as proven private-key recovery.
2. Enroll/identify the Apple Developer team and resolve the app's distribution eligibility. Supply signing credentials through protected release secrets, not chat.
3. Finalize operator/contact details and public privacy policy, then wire its approved URL into the native app and metadata. Complete the Apple questionnaires/review setup against the actual signed build.
4. Run the signed workflow and validate Apple's processing/TestFlight route. Resume the deferred physical acceptance only when the owner authorizes it and devices/accounts are available.

No broker orders, Discord messages, store submissions or tester invitations were made during this work.
