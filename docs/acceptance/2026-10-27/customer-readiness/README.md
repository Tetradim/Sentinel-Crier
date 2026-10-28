# Windows 0.3.1 customer readiness acceptance

Accepted runtime source: `49d77cc94bce82eedf4d4f0bad074026a0cd2261`. Windows release workflow [40630558959](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40630558959) passed and published [0.3.1](https://github.com/Tetradim/Sentinel-Crier/releases/tag/v0.3.1).

The release adds the four selected Windows improvements: one asynchronous update check at startup, a dismissible banner with explicit review/download/install, persistent connection explanations, a read-only connection test, and a Support/version/export dialog. No periodic network checks, silent installation, new trading permissions or Discord test posts were added. Hidden tray startup remains hidden.

Both local and Windows release CI passed 1,188 Python tests with one optional skip. The 62 focused tests cover once-per-launch notices, dismissal and late callbacks, readiness states, bounded account/relay reads, identity/environment validation, cancellation drain, duplicate test prevention and public-only support details. The offline Tk smoke test validated credentials and sanitized support export with no network calls. Review identified an unbounded broker verification read; the final account-only probe owns a client with a total DNS/connect/body deadline, response cap and cancellation drain.

[Public delivery evidence](public-probe.json) confirms the real signed release was available from 0.3.0, its installer downloaded with matching signed size/SHA256, the startup banner coordinator accepted the result, and a 0.3.1 client reported current. The downloaded installer was not executed on the owner PC.

[Installer lifecycle evidence](installer-acceptance.json) covers install, an acceptance-only next patch with the same program payload, downgrade refusal, preserved journals/protected credentials and uninstall on an ephemeral Windows runner. It does not establish a physical customer upgrade or future database migration.

The read-only connection test verifies the selected Alpaca account/environment and an authenticated relay response. It does not prove host-to-receiver execution or Discord delivery. No real broker orders or Discord messages were sent for this change. Apple signing, Webull activation, Microsoft publisher signing and physical device acceptance remain deferred. These customer controls were implemented for Windows; mobile builds remain separate implementations.

All eight CI workflows for the accepted source completed successfully; [source evidence](source-evidence.json) records their URLs. Android customer acceptance initially failed waiting for emulator window focus; the unchanged failed-job rerun passed. No Android behavior was modified for this Windows release.
