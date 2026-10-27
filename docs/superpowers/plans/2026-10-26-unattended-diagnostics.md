# Unattended Windows diagnostics and support export

**Goal:** Improve post-failure investigation without making logging part of execution authorization or blocking the order loop.

**Design:** A dedicated bounded background writer stores small rotating JSON logs. Capture only safe event codes, exception type, stack file/function/line and validated trade/order correlations. Never collect exception messages, HTTP bodies/headers, environment variables, credentials or local variables. Existing durable execution journals remain authoritative. Export only validated diagnostic records and minimal version/status metadata to a new ZIP; exclude raw databases/configuration/secret files. Surface writer failure/dropped records explicitly.

- [ ] Write regressions for message/credential exclusion, rotation, bounded nonblocking admission, writer failure and strict support-bundle contents.
- [ ] Implement diagnostic writer and safe error/event adapters.
- [ ] Wire desktop worker lifecycle, execution failures and optional reporting failures; expose local support export in Health.
- [ ] Run full Python/desktop verification and document limits.

This does not supply remote outage notification, automatic trading restart, broker approval or physical unattended acceptance. A dead PC cannot notify through its own process; an independent remote observer remains separate work.
