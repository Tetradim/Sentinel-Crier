Crier 0.3.0 adds signed Windows update checks, verified installer downloads and private recovery snapshots. Health → Updates & recovery provides the update and backup actions.

Supported update source: 0.2.0. Profile and trade protocol generation remain 1; this release does not introduce a database format migration. Existing order journals, pairing, credentials and settings are retained. Installer acceptance tests installation and an acceptance-only patch version; physical device acceptance is still deferred.

Crier pauses/drains broker work and closes before installation. Existing broker orders remain active. Start Crier manually afterward, verify the selected account and unresolved orders, then reconnect deliberately. Trading never resumes automatically.

Recovery: preserve the original profile and the protected Recovery snapshot. Restore only to a new private folder for inspection. Use the matching or newer application; unsupported profile generations are refused. Do not downgrade or delete order journals to bypass a compatibility check.

Webull Connect trading remains unactivated: the approved resource adapter, inventory recovery, operator activation and real sandbox tests are unfinished. Apple signing and physical cross-network acceptance remain deferred. Optional Windows publisher signing is separate from the Ed25519 update-manifest signature.
