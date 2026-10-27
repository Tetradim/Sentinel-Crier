# Webull outbound response bounds

Continue the approved Webull route by repairing its HTTP boundary before any trading adapter is activated. The resource transport currently calls `arrayBuffer()` before testing the one-MiB limit, which does not bound retained response data. The token transport streams within 64 KiB but waits for cancellation cleanup and does not independently race body reads against abort.

Design: share a small bounded JSON reader between resource and token transports. Enforce actual received-byte limits during reading, validate UTF-8, discard non-success bodies and cancel without awaiting an untrusted stream's cleanup. Race reads against abort; remove listeners and release reader locks in every outcome. Resource requests combine the existing caller signal with a ten-second deadline. Keep exact hosts/signing, no redirects, no retries and generic secret-free errors. This repair does not supply or activate a trading adapter.

- [x] Add failing transport/reader tests for incremental overflow, stalled cancellation, invalid UTF-8, exact byte boundaries and non-success cleanup.
- [x] Implement bounded reader and compose both existing transports; enforce UTF-8 request body byte limits.
- [x] Run Deno tests/lint/type checks, integrated SQL tests and relevant CI; record exact results and commit/push main.

Completed source verification: [acceptance evidence](../../acceptance/2026-10-27/webull-response-bounds/README.md). No resource adapter or service activation was included.
