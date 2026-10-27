# Windows releases and safe updates

The manually dispatched **Windows release** workflow tests the source and builds an
x64 Python-free portable ZIP plus an Inno Setup installer. It uploads the artifacts
for review. Its explicit `publish_update` option controls GitHub Release publication;
the default retains artifacts only. It does not install an update on a user's PC.
Version comes from root `release.json` and must match `pyproject.toml`. Stable
`MAJOR.MINOR.PATCH` versions with components up to 65535 are required; prereleases
and build suffixes are rejected rather than silently losing their ordering.

## Install

Download the release artifact from the workflow for the reviewed commit. Check the
ZIP/installer SHA256 against `SentinelCrier-VERSION-Windows-SHA256SUMS.txt`:

```powershell
Get-FileHash .\SentinelCrier-0.2.0-Windows-Setup.exe -Algorithm SHA256
```

Checksums detect corruption; trust the artifact's source as well. The JSON manifest
records version, Git commit, Windows x64 platform, bundled public connection-service
URL, actual artifact sizes and SHA256 hashes, and Authenticode status. Neither file
contains credentials. This manifest is release evidence, not an automatic update feed.

Run `SentinelCrier-VERSION-Windows-Setup.exe` as your ordinary Windows user. It
installs under `%LOCALAPPDATA%\Programs\SentinelCrier` and creates a Start menu
shortcut. No administrator elevation is required. The installer does not launch the
app automatically. Portable users extract the whole versioned ZIP, preserving the
`SentinelCrier.exe` / `_internal` layout.

## Update and retained state

Version 0.3.0 adds **Health → Updates & recovery** for authenticated update checks,
verified download, protected snapshot and installer handoff. See the complete
[customer and publisher update guide](customer-updates.md). The instructions below
remain the manual installation/recovery path. The unsigned evidence manifest above
is distinct from the new Ed25519-signed `SentinelCrier-update.json` update catalog.

1. Pause new entries, review unresolved broker orders, disconnect, and close Crier.
   Closing Crier does not cancel existing broker orders.
2. Run the same or a newer installer under the same Windows user. The fixed AppId
   finds the existing per-user install. A running installed executable blocks file
   replacement and asks you to close it; the installer never forcibly closes it.
3. Start Crier yourself and confirm the account, pairing, paused entries, and
   execution journal before reconnecting or enabling new entries.

Program files are separate from `%LOCALAPPDATA%\SentinelCrier\Desktop`. Installation,
updates and uninstall do not delete that data directory, its journals, pairing,
settings or credentials. Credentials remain Windows DPAPI protected for the same
Windows user; moving a data backup to another user or PC does not make it usable.
For portable updates, extract into a fresh program folder, close the old app and
launch the new executable. The same user data path is reused automatically.

The installer blocks a version older than its registered installed release. Portable
users must also avoid downgrades: journal/configuration compatibility with an older
program is unsupported. Never delete a journal to bypass a compatibility error.
Any future data schema migration must reject unsupported formats before connecting
or placing orders and supply a documented recovery path. Back up the closed data
folder before such a migration. Keep the newer program or reinstall it if a program
update fails; preserve the data folder for diagnosis.

Uninstall from Windows Settings removes registered program files and the shortcut;
it deliberately retains all user data. Secure erasure of saved credentials/data is
a separate, explicit user operation after reconciling broker orders and journals.

## Build and signing

On Windows x64 with Python 3.11+, Tcl/Tk and Inno Setup 6 installed:

```powershell
python -m pip install -e ".[test,desktop-build]"
python -m pytest -q
powershell -ExecutionPolicy Bypass -File desktop/release.ps1
```

Use `-Python` or `-ISCC` to select the Python executable/compiler. Outputs are in
`dist/release/`; `desktop/build.ps1` also retains the original developer portable ZIP.
The build checks Python is x64 and runs the packaged offline UI/DPAPI smoke test.
The checked-in connection-service JSON and release metadata travel with the app.
Do not build distributables from a dirty checkout: the recorded Git commit identifies
committed source, so uncommitted changes would make that provenance incomplete.

Without a signing certificate the release is explicitly **unsigned** and Windows may
show publisher/reputation warnings. No trusted certificate is created or installed.
For real signing, configure `WINDOWS_SIGNING_PFX_BASE64` and
`WINDOWS_SIGNING_PFX_PASSWORD` secrets on the `windows-release` GitHub environment.
Use a legitimate code-signing certificate whose provider supports PFX signing; an
HSM-only provider needs a separate integration. The workflow writes the certificate
only to a temporary runner file, imports its key ephemerally, signs the app before
zipping and the finished installer, and deletes the PFX in a `finally` block. Signing
must return `Valid` or the build fails. Secrets are never placed in release artifacts.

Local signing can supply `-SigningPfxPath` and set the password environment variable.
Use a trusted RFC3161/Authenticode-compatible timestamp service through
`-TimestampServer` as appropriate for your certificate provider. A signed manifest
means the app launcher and installer have valid Authenticode signatures; it does not
mean every third-party runtime file has been re-signed by this project.

## Verification status and acceptance

Source tests cover version validation, manifest contents/hashes, packaging of public
configuration, and installer program/data boundaries. CI must compile the actual
installer and produce artifacts; a source test pass alone does not prove installation.
Before calling a release accepted, manually test on an ordinary Windows account:
install without admin rights; connect to paper; close/update while retaining the
pairing, credentials and journal; verify running-app and downgrade rejection; uninstall
and confirm the data remains. Physical iPhone/PC mirroring and installer acceptance
are deferred until those devices and the reviewed release artifact are available.
No Apple developer account is needed to build this Windows release.

Inno Setup's [version parsing](https://jrsoftware.org/ishelp/topic_isxfunc_strtoversion.htm)
and [comparison](https://jrsoftware.org/ishelp/topic_isxfunc_comparepackedversion.htm)
are used for the installed-version downgrade guard.
