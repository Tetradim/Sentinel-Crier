# Relay operations

Run the dedicated relay with exactly one Uvicorn worker. Notifications, request metrics, job status, and the process lock are local to that process. Restarting resets uptime and metrics. Use a persistent data volume for `CRIER_DATA_DIR`; a running container with an ephemeral filesystem is not a durable relay.

## Readiness

`GET /health` is public. HTTP 200 means the relay can open its SQLite database, query the required columns in all six relay tables, acquire the SQLite write lock, create and flush a temporary file on the data volume, and meet both configured free-space thresholds. Missing tables or required columns, database query/lock errors, disk probe failures, and insufficient disk space return HTTP 503. The response contains only `status` (`ok` or `unavailable`), `pairing_enabled`, and `protocol`.

This is a dependency readiness check, not a full SQLite integrity check or an end-to-end delivery guarantee. It does not publish events or call a broker, paid provider, or external service. A prolonged write transaction can make readiness fail while the database is busy.

Configure thresholds before starting the process:

| Variable | Default | Meaning |
| --- | --- | --- |
| `CRIER_RELAY_MIN_FREE_BYTES` | `67108864` | Minimum free bytes on the data volume (64 MiB). |
| `CRIER_RELAY_MIN_FREE_PERCENT` | `1` | Minimum free percentage on the data volume. |

Both thresholds must pass. Set either to `0` to disable that threshold. Negative bytes, nonfinite percentages, or percentages outside 0â€“100 are rejected at startup. Reserve additional room for backups according to actual traffic and retention; the defaults are a basic readiness floor.

## Owner status and metrics

`GET /api/ops` requires `Authorization: Bearer <owner access token>`. Host tokens, receiver tokens, and unauthenticated requests receive HTTP 401. Keep the owner credential in a secret store; never put it in a URL. The endpoint returns HTTP 200 when ready and HTTP 503 when degraded, with:

- Database readiness and disk readiness, total/used/free bytes, free percentage, and configured thresholds.
- Aggregate channel, receiver, and event counts when the database query succeeds. Counts include revoked channels/receivers and retained events.
- Process uptime in seconds.
- Request counts grouped by a fixed route template, HTTP method, and response status, with cumulative and maximum latency in seconds. These measure complete requests, including time spent long polling. An operations request appears in the next snapshot after it completes.
- Last completion time (Unix seconds) and success boolean for operational jobs reported through the scheduling hook.

Status never includes tokens, token digests, channel/receiver IDs, account names, event payloads, SQL error details, or data-volume paths. Metrics retain route templates such as `/api/sync/revoke/{identity}`; unmatched paths use a single `unmatched` label. They never retain raw URLs, query parameters, headers, or client IP addresses. Methods outside the fixed standard-method set share `OTHER`. Body-size rejection can occur before routing and uses `unmatched`. Metrics are in-memory JSON aggregates, not a public Prometheus endpoint.

The server disables Uvicorn access logging. If a reverse proxy adds its own access logs, configure them to omit query strings and credentials. All operational responses use the relay's `Cache-Control: no-store` policy.

## Scheduling integration

The application exposes `app.state.relay` and `app.state.relay_ops` for in-process maintenance. `relay_ops.readiness()` is the same check used by public health. `relay_ops.record_job(name, success)` accepts only `health`, `backup`, or `retention` and retains only completion time and success, with no exception text or file paths. Job scheduling and backup policy are configured by the service lifecycle; these hooks do not create additional workers or external monitors.

A failed or stale job should be investigated separately from dependency readiness: `/health` does not promise a recent backup. Verify backups using the documented restore procedure and keep copies outside the data volume when durable recovery is required.

## Local verification

Run `python -m pytest tests/test_connection_ops.py tests/test_connection_server.py -q` without live endpoints. Tests cover owner/host/receiver isolation, minimal public health, missing tables and columns, database failure, disk write failure, both disk thresholds, redacted route metrics, body rejection, and operational job hooks.

Public readiness checks are serialized and cached for two seconds to prevent concurrent unauthenticated probes from repeatedly acquiring a SQLite write lock or forcing disk syncs. SQLite readiness lock acquisition is bounded to 100 ms; a busy service may report temporarily unready. Operator snapshots perform a fresh check.
