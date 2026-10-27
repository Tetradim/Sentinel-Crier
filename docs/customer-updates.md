# Windows updates and recovery

Open **Health → Updates & recovery**. Choose **Check for updates**, **Download verified update**, then **Install update**. Review the release notes before installation. Cancel download is available; checks never interrupt brokerage execution.

Install update disconnects and drains Crier's broker workers, closes their stores, creates and verifies a private recovery snapshot, then closes Crier. A separate Windows helper waits for the process to exit, verifies the signed manifest's expected SHA256 again and opens the normal installer. It holds file/directory handles through launch to prevent replacement. The installer preserves the active profile. Start Crier manually afterward; confirm the account and unresolved orders before reconnecting. Existing broker orders remain active throughout. Trading never resumes automatically.

The first installation of 0.3.0 is a normal manual installer update: older builds have no in-app updater. Subsequent compatible signed releases can use this flow. If no release is published, the screen says so; it does not install an Actions artifact or an unsigned replacement. Downloads allow thirty seconds for metadata, ten minutes for installers and fifteen seconds of socket inactivity. Interrupted/corrupt downloads are refused and partial files removed.

## What is verified

Before the first manual upgrade from an older build, close Crier and keep a private copy of its `Desktop` data folder. Older versions cannot create the new automatic snapshot themselves.

The app pins `Tetradim/Sentinel-Crier` and its bundled Ed25519 public release keys. The signature covers exact manifest bytes: release version/source, installer URL, size/SHA256, supported source versions, profile/protocol generation and release notes. Repository/tag/asset URLs are constrained to the expected GitHub release; redirects are limited to the explicit GitHub asset host. Duplicate JSON keys, unknown formats, incompatible generations, unsupported upgrade ranges and downgrades are refused. The latest version reports current even though it is outside its own older-source upgrade range.

Ed25519 release authentication is separate from Microsoft's publisher reputation. If publisher certificate SHA256 fingerprints are configured in the bundled public policy, the helper additionally requires a valid matching Authenticode signer. An empty publisher list does not invent a Microsoft certificate: Windows can still show publisher/reputation warnings. Obtaining a publisher certificate remains an operator task.

No runtime option can point customers at another repository or replace trust keys. Fork maintainers must establish their own signing authority and rebuild/review the pinned policy. Rotation must be explicit and preserve a trusted upgrade path; replacing keys or reinstalling an unrelated fork is not automatic continuity.

## Recovery snapshots

Normal profile: `%LOCALAPPDATA%\SentinelCrier\Desktop`. Backups: `%LOCALAPPDATA%\SentinelCrier\Recovery`. Verified downloads and install-result receipts: `%LOCALAPPDATA%\SentinelCrier\Updates`.

Snapshots include journals, settings, pairing and protected credential ciphertext. SQLite's backup API includes committed WAL data. Backups have user-only Windows directory permissions and integrity manifests. They contain private account data; do not attach them to public support issues. Existing Windows DPAPI credentials remain bound to the original Windows user. Integrity checks detect damage, not a maliciously rewritten backup from an untrusted person.

If an update fails:

1. Keep the original profile and recovery folder. Installer failure does not authorize deleting either.
2. Reinstall the matching or newer reviewed Crier installer; no downgrade is supported. Start disconnected and inspect unresolved orders.
3. Use **Verify recovery backup** to validate a snapshot. **Restore backup to a new folder** creates a separate profile for inspection, preserving the active profile.
4. If restoring that profile is necessary, fully quit Crier. In File Explorer rename the original `Desktop` folder to a retained name such as `Desktop-before-recovery`. Move the verified restored folder into `%LOCALAPPDATA%\SentinelCrier` and name it `Desktop`. Preserve the original and snapshot until reconciliation is complete.
5. Start Crier manually using a release that supports that profile generation. Verify broker/account identity and reconcile existing broker orders before enabling entries. Restoring local history cannot reverse an order already sent to a broker.

There is deliberately no automatic rollback into an older trading journal or automatic reconnection after recovery. A newer/unknown profile-generation marker is refused before DesktopWorker opens stores or connects. Generation 1 remains current; this release adds no database-format migration. Future migrations must supply their own fixtures, compatible source ranges and recovery evidence.

## Publishing an update

Update trust is provisioned: only the public verification key is in `crier/update-policy.json`; the encrypted private key/password are held in repository Actions secrets. A local backup is Windows-user DPAPI protected under `%LOCALAPPDATA%\SentinelCrier\ReleaseSigning\publisher-key.secret`. Do not move it into the repository or send it in chat. A backup tied to this Windows user is not an independent disaster-recovery copy. The one-time bootstrap refuses to overwrite existing signing authority.

For a new release, increment `release.json` and `pyproject.toml` together, synchronize `ios/ReleaseVersion.xcconfig`, and increase the Android version code when shipping an Android build. Update `desktop/UPDATE_NOTES.md` with migration/recovery details. Run the **Windows release** workflow on reviewed `main`, declaring the tested minimum/maximum source versions. The target must be newer than that range.

The workflow builds/tests packages and installer lifecycle, signs `SentinelCrier-update.json`, and retains the signed catalog separately from the Windows installer artifacts. With **publish_update=false**, it publishes no GitHub Release and customers see no update. With **publish_update=true**, a separate limited-permission job publishes the reviewed files under `vVERSION`; only then can the in-app checker discover them. Do not reuse a release version for changed binaries.

Initial release/signing uses `CRIER_UPDATE_PRIVATE_KEY_PEM`, `CRIER_UPDATE_KEY_PASSWORD`, `CRIER_UPDATE_KEY_ID`. Windows Authenticode uses the separately optional existing PFX workflow configuration. None of those private values are packaged into Crier. No real release was published merely by adding this feature.

Apple enrollment/signing, TestFlight/App Store distribution, real publisher trust, physical install/update trials and real broker acceptance remain separate prerequisites. This Windows feature does not add an Android APK auto-updater or complete iPhone distribution.
