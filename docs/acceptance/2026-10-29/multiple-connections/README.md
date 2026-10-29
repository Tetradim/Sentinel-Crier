# Multiple connection acceptance

Accepted runtime source: `1f48e403753b4a06daf8aa42939c49eac1e1ec63`, version 0.4.0.

Scope: retained concurrent Host/Receive routes with independent Alpaca accounts, scoped credentials/pairing/journals/settings/cursors, safe selected-route editing and all-route shutdown. Original evidence stays in place. Same destination account/environment in different routes is refused, including after disconnect/restart or loss of saved credentials. Several hosts sharing one account and additional broker executors remain unfinished.

Review repaired Android shared Alerts/customer-session crossover by restricting those workflows to the durable original route; account claim poisoning and credentialless journal rebinding; legacy account recovery; untracked iOS jobs during stop; and duplicate Windows log rotation. A packaged smoke failure exposed missing per-route startup evidence; a reproduced regression now verifies each route's support export contains its own startup record. Text encoding was normalized before the final build.

Synthetic coverage includes same source event to two distinct accounts, duplicate suppression, exit isolation, route selection while requests are queued, saved history/corruption/migration, durable collision rejection and shutdown cancellation. Tests do not submit real broker orders, post Discord messages or establish physical cross-network acceptance.

The iOS/Android additional-route capability limits and installation instructions are in [multiple connections](../../../multiple-connections.md). iOS signed installation, actual mobile lifecycle acceptance, broker-UI reconciliation and Webull/Tradier resource adapters remain unfinished. Do not describe all D.1 scope as complete.


Final-source verification passed all seven triggered CI workflows: 1,205 Python tests (one optional skip) in the Windows release job, 181 native iOS tests, Android unit/build checks, customer UI journeys on all three platforms, simulator and unsigned hardware compilation, Windows packaged smoke tests, and installer lifecycle acceptance. See [source evidence](source-evidence.json).

[Windows 0.4.0](https://github.com/Tetradim/Sentinel-Crier/releases/tag/v0.4.0) is published. [Public update evidence](public-probe.json) records actual signed discovery from 0.3.1, installer size/SHA256 verification, and 0.4.0 reporting current. The installer was downloaded but not executed on the owner's PC. [Installer acceptance](installer-acceptance.json) covers the ephemeral Windows runner; its acceptance-only next patch uses the same payload and is not a future migration claim.
