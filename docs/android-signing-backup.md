# Portable Android signing backup

The source `%LOCALAPPDATA%/SentinelCrier/Signing/android-signing.secret` uses
Windows user-bound DPAPI. Copying that record alone does not provide portable
recovery. The helper re-exports the existing private key as a standard PKCS12
keystore encrypted with a **new owner-entered passphrase**. It does not create a
replacement signing identity or change the original keystore or CI secrets.

Run on the trusted Windows account holding the source identity, with Python and
JDK `keytool` installed. Choose a **new directory** under trusted owner-controlled
storage, outside the checkout and cloud sync. Even an existing empty directory
is refused, so a typo cannot overwrite an earlier backup. The parent must exist.

```powershell
python scripts/android-signing-backup.py --destination 'E:\SentinelCrier-Signing-Backup'
```

The default uses a terminal with two hidden `getpass` prompts. Redirected input
and visible-input fallback are refused. Use `--gui` for two masked Tk password
dialogs, including when launching with `pythonw`:

```powershell
pythonw scripts/android-signing-backup.py --gui --destination 'E:\SentinelCrier-Signing-Backup'
```

Select a unique strong passphrase of at least 16 characters and retain it in
separate owner-controlled custody. Cancel or mismatched confirmation creates no
backup. There is no command-line or file option for the new password. Passwords
reach `keytool` only through its child-process environment using `:env` options;
they are not placed in command arguments, output files, or error messages. This
does not defend against a compromised administrator, process memory inspection,
or a malicious JDK. Use a trusted machine, JDK, and destination.

The helper verifies the source alias is a `PrivateKeyEntry` and its certificate
matches `android-certificate-sha256.txt`, imports the private key using both
source store/key passwords, then reopens the exported private-key entry with
the new password and checks the same fingerprint. The source credential schema
is `alias` and `password`; both store and key use that source password.

The completed directory contains:

- `android-release-backup.p12`: encrypted private key and certificate.
- `manifest.json`: public alias, certificate fingerprint, keystore hash, timestamp.
- `SHA256SUMS.txt`: keystore checksum.
- `RESTORE.txt`: recovery and signing-drill instructions.

The destination uses mode 0700 and keystore mode 0600 where supported. Windows
ACLs inherit from its parent; choose an owner-only parent. A failed export cleans
only named files created inside its newly created directory and never recursively
deletes the source or an existing destination. If an unrelated file appears in
that directory during cleanup it survives. Abrupt process/machine termination
can leave partial output; treat a missing manifest as incomplete and inspect it
manually before choosing a fresh destination. Backups remain sensitive even
though encrypted. Never commit them or upload them as release artifacts.

`This PC\Galaxy Tab A9+ 5G` is an MTP device, not a filesystem drive that Python
can write through a drive-letter path. For such storage, first export to a new
folder under an owner-only local parent, then copy the completed directory using
Explorer/MTP. Copy it back to a separate temporary folder and recompute the
PKCS12 SHA-256 against the trusted manifest before counting that offline copy as
verified. The helper itself does not transfer to MTP or certify offline custody.

Retain the public pin independently of the backup. The hash/manifest detect
corruption, but a substituted directory can include a substituted manifest.
On a separate trusted recovery machine, follow `RESTORE.txt`, provide the backup
passphrase for both store and key, sign a disposable candidate, and verify its
certificate against the independent pin before modifying production CI.

Automated tests generate a disposable synthetic identity and prove re-encryption
and reopening with the same certificate, plus refusal/cleanup and password-leak
regressions. They do not export the real identity or select an owner password.
The owner password entry, offline transfer, checksum comparison, and separate
machine signing drill remain operational release evidence.
