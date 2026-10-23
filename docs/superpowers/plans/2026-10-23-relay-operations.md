# Phase 3 relay operations implementation

Goal: make the existing single-worker HTTPS relay deployable, recoverable, and measurable. Actual public deployment requires an owner-selected hosting account and endpoint.

1. Add consistent online SQLite snapshots, integrity/checksum verification, retention, and lock-protected restore, with real recovery tests (`crier/relay_backup.py`). Backups contain pairing credentials and require protected storage.
2. Add public readiness and owner-only redacted operational status, disk thresholds, request metrics and degradation tests (`crier/relay_ops.py`, `connection_server.py`).
3. Add scheduled backups and a broker-free deployment image, configured persistent directories and a recovery runbook. No paid service is created without an explicit hosting choice.
4. Run a synthetic HTTP/ASGI load/reconnect/restart/revocation benchmark and retain latency/capacity measurements with their local-environment limits (`scripts/benchmark_relay.py`).
5. Bundle the public connection origin consistently in Android/iOS/Windows; add validation of an operator-supplied HTTPS endpoint. Keep the origin empty until a real service exists.
6. Review changes, run backend tests and relevant native builds, commit/push main. Provision and exercise real remote clients when hosting credentials/endpoint are available. Phase 3 stays incomplete until the remote-service gate passes.

Validation: backup consistency/corruption/restore tests, auth-isolated metrics, low-disk readiness, shared-origin configuration tests, and declared-load benchmark. No broker orders or Discord posts.
