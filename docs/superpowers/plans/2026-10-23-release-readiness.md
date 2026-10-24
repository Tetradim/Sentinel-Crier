# Phase 4 release readiness

The owner explicitly deferred physical tests and requested the next roadmap item. Deferred tests are not passing evidence. Apple Developer enrollment is absent, so signed iPhone packages and TestFlight submission remain externally blocked.

1. Centralize candidate version 0.2.0 in release.json. Android code 2 upgrades prior code 1; iOS build numbers must increase relative to the owner's uploaded build history.
2. Produce versioned Windows installer and portable archive, checksums and provenance, preserving all user journals and credentials under the existing data folder. Mark packages unsigned unless a real publisher certificate is supplied.
3. Add Android signed APK/AAB workflow with protected persistent signing identity, strict no-debug-key fallback and signature verification; verify existing data identity is retained. Establish a protected local signing identity if none exists; never commit keys/passwords.
4. Harden iPhone profile/identity checks and signed artifact provenance, prepare explicit TestFlight upload path and customer metadata requirements. Do not create a fake signing identity or claim public distribution approval.
5. Test migration/upgrade boundaries, packaging configuration and release tooling. Run relevant CI, retain artifacts, and push direct to main. Record exact completed artifacts versus missing external credentials and deferred acceptance.
