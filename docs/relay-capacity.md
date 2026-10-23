# Broker-free relay load and recovery exercise

Run from the repository root with the project's Python dependencies installed:

```powershell
python -m scripts.benchmark_relay --hosts 1 --followers 10 --events 50 --output relay-benchmark.json
python -m pytest tests/test_relay_benchmark.py -q
```

`--followers` and `--events` are per host. At least two events are required. `--timeout` bounds each of two load phases (default 60 seconds). Each invocation creates and removes an isolated temporary SQLite database. The JSON output contains aggregate counts, timings, gate status codes and environment information. It never emits pairing credentials, invitations or event bodies. An aborted run returns exit code 1 and a redacted error type; a completed run with failed checks also returns 1. Keep the full command, JSON, machine details and application revision together when comparing runs.

The harness sends actual HTTP requests through `httpx.ASGITransport` into `create_connection_app`, including the service's body limit, middleware, validation, authentication, router and SQLite persistence. It enters the application's lifespan and uses the standalone relay application, which has no brokerage worker. It does not use the live hosting service, broker credentials or broker APIs.

Each host is created through public Host setup. Each follower consumes its own single-use invitation through Receive and gets an independent credential before publishing begins. Synthetic source addresses distinguish simulated devices and invitation requests; this honors existing per-source setup gates while allowing a configurable aggregate load. It does not model a large group behind a single NAT address. The load phase runs followers concurrently with publishers, using long polling (`wait=1`), cursor advancement and paginated delivery. Each host publishes sequential deterministic UUID events, yielding between requests. Event timestamps are freshly generated with a valid 30-second lifetime; expired-at-receipt events count as failures. Payload identity is deterministic; credentials, timestamps and timing measurements vary.

Between phases all HTTP clients and application lifespan contexts close. A new application instance opens the same SQLite file. Each follower reconnects with its prior credential and cursor; a read after that cursor must remain empty. Reading from zero must replay precisely the previously published events, including pagination. Republishing the first event must return its original cursor. The remaining half of the events must reach all followers after reconnection. Finally one receiver is revoked; its credential must fail while the other receivers on its channel still work. This verifies application recreation and reconnect persistence. It does not simulate a killed process, machine crash, disk failure or restart during an in-flight transaction.

The gate checks assert actual service semantics: missing authorization and a host credential used to read both return 401; an empty event and a malformed invitation return 422; the twenty-first malformed Receive attempt from one source within its rate window returns 429. Receive's malformed code is charged against its rate gate. These status codes are expected checks and are not delivery failures.

Metrics have these definitions:

- Expected deliveries: hosts Ã— followers per host Ã— events per host. Successful deliveries count distinct verified `(host, follower, event)` observations. Duplicates, foreign events, changed contents and request errors abort the run.
- Transport latency: monotonic elapsed time from immediately before the host's publish request to handling the delivered event after the follower's HTTP response. It includes HTTP/ASGI processing, SQLite work, event-loop scheduling and client processing. It excludes pairing and recovery checks. It is not broker execution latency.
- Queue age: wall-clock time from synthetic event creation to follower observation. This is an end-to-end age proxy, not an instrumented server-only queue residence measurement. Both timestamps originate on the same machine.
- Percentiles: nearest rank over all individual follower deliveries; no interpolation. `max` is the largest observed sample.
- Load duration: sum of both concurrent load phases, including the brief reader warmup. Deliveries/second divides successful deliveries by that duration. Total duration also includes setup, restart/replay, revocation and gate checks.

## Local measured sample

One run on 2026-10-23 used Python 3.11.9, Windows `Windows-10-10.0.28000-SP0`, httpx 0.28.1, one host, ten followers and fifty events per host. Its measured aggregate output was:

```json
{
  "expected_deliveries": 500,
  "successful_deliveries": 500,
  "failures": [],
  "transport_latency_ms": {
    "count": 500,
    "p50": 40.7619999605231,
    "p95": 53.448099992237985,
    "p99": 60.02389994682744,
    "max": 63.985399960074574
  },
  "queue_age_ms": {
    "count": 500,
    "p50": 40.807,
    "p95": 53.519,
    "p99": 59.724,
    "max": 63.519000000000005
  },
  "load_duration_seconds": 1.7848965000011958,
  "duration_seconds": 2.488269399967976,
  "deliveries_per_second": 280.12828755037896,
  "recovery": {
    "restart_cursor_preserved": true,
    "replay_preserved": true,
    "duplicate_publish_preserved": true,
    "independent_revocation": true
  },
  "gates": {
    "missing_auth": 401,
    "wrong_role": 401,
    "malformed_event": 422,
    "malformed_invitation": 422,
    "receive_rate_limit": 429
  }
}
```

This demonstrates completion of this declared local workload only. It is not a maximum capacity measurement, sustained soak test, latency guarantee or production sizing recommendation. In-process ASGI excludes sockets, DNS, TLS, WAN latency, proxies, hosting resource limits and actual client runtime behavior. Client and server share one Python process and event loop. The service's deployment model remains one worker because long-poll notifications are in process. Establish hosted capacity separately with representative machines, network clients, sustained traffic, storage limits and operational monitoring before making a supported concurrency claim.

## Integration rerun

October 23, 2026, Python 3.11.9 / Windows / httpx 0.28.1: 1 host, 10 followers, 50 events delivered 500/500 copies, zero failures. In-process transport latency p50 45.883 ms, p95 61.124 ms, p99 306.693 ms, maximum 323.491 ms; load duration 2.235 seconds. These are measured local results, including application-level scheduling and SQLite overhead, not a customer network SLA. Redacted JSON is retained locally at `dist/phase3-relay-benchmark.json`.
