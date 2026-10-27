# Windows technical logs and support bundles

The Windows app now records technical errors in a bounded background writer, separate from the durable execution journals. Logs are under `%LOCALAPPDATA%/SentinelCrier/Desktop/logs/` for the normal desktop profile. The current file and up to three backups rotate at approximately 2 MiB each; the bounded queue holds at most 512 records.

Recorded evidence includes UTC time, a fixed event code, exception type, stack file/function/line and validated trade/order correlations when available. Exception messages, HTTP headers/bodies, environment variables, credentials, pairing tokens and local variables are excluded by construction. No general HTTP debug logger is enabled. Repeated errors with the same code/type/trade are suppressed for 30 seconds; health state transitions are recorded separately.

## Export when something fails

Open **Health → Connections → Export support bundle**, then choose a new ZIP filename. Export works while disconnected. The bundle contains validated technical log records and minimal application/platform/logging metadata. Packaged builds include their public version/source commit resource. It excludes raw SQLite databases, configuration, credential files and general account/portfolio exports. Review technical IDs before sharing through the support route.

The Health screen reports writer availability and dropped/suppressed counts. Export refuses to pretend success if the writer cannot flush within its bounded wait. Existing trade JSON/CSV exports remain separate and are still needed when investigating fill quantities or prices; the technical bundle intentionally does not copy the entire account history.

## Behavior during failure

- Logging admission never waits for disk I/O. A full queue drops technical evidence and increments its counter.
- Storage/writer failure is reported without authorizing, canceling or retrying any broker operation.
- Execution/reconciliation errors and optional copy-report/metadata failures now retain safe stack locations.
- Desktop background-operation failures, async-loop failures and UI callback failures are recorded where the application can observe them.
- A fatal window-loop exception requests the existing normal worker shutdown, pausing new entries and draining in-flight work before stopping the non-daemon execution loop. It does not liquidate broker holdings.
- Normal shutdown attempts to drain the logger. Power loss, forced termination, full storage or a hung filesystem can still leave incomplete evidence.

This is **local post-failure evidence**, not a crash-proof audit service or remote monitoring system. A powered-off or dead PC cannot send its own outage notification. Independent stale-heartbeat notification, real unattended recovery trials and explicit restart/reconnect policy remain separate work. Windows still starts disconnected at sign-in; no automatic trading restart has been enabled.

The iPhone's Webull journal and server authorization records have their own scope. This Windows feature does not add native iOS crash collection or claim complete server incident logging. No diagnostic export automatically sends a Discord message, email or support ticket.
