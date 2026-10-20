# Direct mirroring verification — 2026-10-20

Implementation tested: `09fb8d4ee43cbee9e3ae0d88aa1cd4eb12452e74`.

- Local Python: **228 passed**, one existing Starlette/httpx deprecation warning.
- Native simulator: **38 tests passed**, zero failures. Includes HTTPS pairing validation, exact option/partial quantity, source-account-scoped event identity, and rejection of mirrored or multi-leg source orders.
- iOS simulator build passed.
- Receiver tests cover duplicate delivery across restart, altered replay, concurrent duplicates, incremental fills, pause/resume, stale/future timestamps, environment/account mismatch, revoked tokens, holdings checks, unknown submission reconciliation and owner-only recovery IDs.
- Console JavaScript syntax and Git whitespace checks passed.

CI: [native and backend safety checks](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39410444831), [iOS build](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39410444890).

No real or paper brokerage orders and no Discord messages were sent. Broker tests use fake clients/HTTP transports. A physical-device end-to-end paper trial is still required after configuring receiver credentials, an HTTPS address and a signed iPhone installation.

Supported path: active customer iPhone → paired PC receiver → receiving Alpaca account. No Discord parsing or per-trade approvals. Source executions are observed during foreground polling, approximately two seconds plus network/broker latency; this is not instantaneous order-button interception. The receiver sends day limit orders and cannot guarantee matching fills or prices. Phone-only receiving/execution, background iOS monitoring, Webull and multi-leg mirroring are not implemented.

See [setup instructions](direct-mirroring.md). Preserve both journals during recovery. Follow is opt-in per pairing; pause/revoke does not cancel existing broker orders.
