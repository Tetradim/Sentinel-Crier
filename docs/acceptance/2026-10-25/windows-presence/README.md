# H.4 Windows presence acceptance

Source `7f8efe3` adds optional Windows notification-area presence and current-user sign-in startup. The [source-bound report](source-evidence.json) records final Python results, CI revisions and exact preserved artifact hashes. Installer and packaged smoke reports distinguish hosted-runner checks from physical-customer acceptance.

## Implemented behavior

- Both options default off. Tray mode is a nonsecret atomic preference. Startup registration is written only after an explicit checkbox action and only for a packaged Windows executable.
- Every launch starts disconnected. Sign-in registration contains only the executable and `--startup`, with no credentials, account IDs or entry authorization. Restart and reconnect retain the existing permission gates.
- Native callbacks enqueue Show Crier, Pause new entries, or Quit Crier. Tk handles these on its own thread. There is no tray action to enable entries.
- Closing hides only with an opted-in, ready tray. Initial failure and unexpected tray shutdown keep or restore the window. A shutdown fence handles native setup completing late, and disabling tray restores the window.
- Quit uses the existing disconnect/in-flight flow before stopping the icon and worker. Cancellation of the quit confirmation leaves Crier accessible.
- The per-user installer leaves startup off. Explicit opt-in survives an in-place upgrade. Uninstall deletes only the startup command matching its own executable; journals and credentials retain their existing preservation behavior.
- Windows ZIP inspection verified all 13 tray-library source files against the pinned installed distribution, and its license/build files against upstream v0.19.5. The package also includes Pillow/six notices and a [dependency manifest](windows-third-party-bundle.json).

## Verification boundaries

Local verification passed **867 Python tests**, with one optional Webull SDK skip, and **62 focused lifecycle/UI/installer tests**. The final CI matrix passed **867 tests/one skip** on Windows and **837/31 skips** on each Linux environment. The release environment passed **798/three optional skips**. The packaged native tray became ready and stopped successfully with zero network calls. Installed startup default-off, explicit opt-in, upgrade preservation and uninstall cleanup passed on the hosted Windows runner, with synthetic journals and credentials.

No broker order, Discord message, service deployment or actual Windows sign-in was performed. Physical Explorer/taskbar interactions, device tests, signing and provider activation remain deferred. H.5 deliberate sizing and entry/exit policy design remains implementation work; H.4 changes no pricing or trading defaults.
