# Customer update delivery and recovery

Implement the update work approved after the installer assessment. Windows gets an explicit Check for updates → verified download → prepare/close/install flow. Server-only updates remain independent. Apple signing/distribution and real publisher credentials are external prerequisites, not invented trust.

Trust: pin the Tetradim/Sentinel-Crier release repository and a checked-in public update policy. Detached Ed25519 signatures cover exact manifest bytes, including version, installer URL/hash/size, compatibility and release identity. Release tooling signs only with an operator-provided private key; no private key is bundled or generated as an implicit trusted authority. Empty trust configuration refuses installation with a clear explanation. Downloads are HTTPS, bounded, no redirects except specifically validated GitHub release-asset hosts, and hashes are verified before any execution. Authenticode must also be valid for the pinned publisher certificate when configured. Never execute an unsigned/unverified candidate.

Lifecycle: updates are explicit user actions; no execution during active brokerage work. Use normal disconnect/drain, then a closed-profile snapshot. Backups include durable journals/settings/DPAPI ciphertext in protected local storage, never support exports or external uploads. Atomic backup manifests validate integrity; SQLite backup APIs include WAL data. Restore is explicit, offline, refuses overwrite of current profile and validates paths/hashes/formats. No automatic downgrade or automatic trading reconnect.

Compatibility: signed manifests declare supported update-source versions and profile/protocol generations. Refuse incompatible/unknown versions before installer launch. A persistent profile-generation gate prevents newer data from being opened by unsupported newer code; established journal migrations retain their checks. Releases must carry migration/recovery notes and a tested accepted-source range. Do not claim arbitrary future schema migrations are validated.

Tasks:
- [ ] Signed manifest/pinned-policy verification, bounded GitHub release discovery/download, secure staged installer verification and tests.
- [ ] Protected offline profile backup/integrity/restore and profile compatibility preflight, with meaningful corruption/symlink/WAL tests.
- [ ] Windows UI update actions and safe installation handoff integrated with existing shutdown; no silent reconnect.
- [ ] Release-signing/publication tooling, workflow support and operator/customer documentation.
- [ ] Run source, packaged and installer verification; document exact source evidence and unprovisioned signing/distribution prerequisites.
