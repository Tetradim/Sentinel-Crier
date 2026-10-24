# Android candidate release

Candidate version and version code come from root `release.json`. The stable application ID remains `com.sentinel.crier`; new distributed version codes must exceed every prior distributed code. Physical acceptance is deferred by the owner, not passed.

The manually triggered **Android release packaging** workflow compiles/tests without signing, proves unsigned release packaging fails closed, then builds an operator-signed APK and AAB using the `android-signing` environment. Four protected secrets are required: `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. No debug key is substituted for a missing release identity.

A persistent Android signing identity was provisioned locally for this project under `%LOCALAPPDATA%/SentinelCrier/Signing/`. Its password record is protected with Windows user-bound DPAPI, and its directory has an owner-only ACL. An encrypted keystore copy is configured as a GitHub environment secret. Keep an encrypted offline backup of this identity; losing the key prevents signing compatible future updates. The [interactive backup helper](android-signing-backup.md) re-encrypts a portable PKCS12 copy under an owner-entered passphrase, independent of this Windows user's DPAPI record. Keep that passphrase separately. Never commit or paste either into source or release notes.

Public certificate SHA-256:

`1ff6c2bc5857d0de21b5fb286e11dea8f5a85e3b4b92cbba3e94186b89b1c2a6`

The release manifest verifies APK and AAB signatures against this identity and records artifact checksums, source commit, version code and provenance. Android signing is not an independent publisher certification or Play Store approval. Install the APK directly for candidate testing; AAB is a store-upload artifact, not a directly installable app.

## Updates and existing debug installs

Updates signed with the same release certificate and a higher version code retain the existing Android application data and Keystore identities. A previously installed debug APK uses a different signing identity and cannot be upgraded in place with this release. Do not uninstall an installation holding unresolved orders or unreviewed deliveries to bypass this error: uninstalling removes its local journal and may destroy credential recovery. Reconcile the existing installation first and retain its exported evidence before planning a fresh installation. Cross-signature migration is not implemented.

The release workflow does not publish to Google Play or place trades. Real-device acceptance remains deferred; signature/build verification does not substitute for it.
