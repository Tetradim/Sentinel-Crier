# Authorization service and Windows support evidence

This acceptance covers source implementation and automated checks, not operational Webull trading or a customer handoff. Exact revisions, test counts and CI links are recorded in [source evidence](source-evidence.json).

The Webull service now composes authenticated consent initiation, single-use browser tickets, cookie-bound callbacks, encrypted credential custody, refresh, local removal, request admission and an Edge Function entry point. Native iPhone consent uses the configured gateway launch URL. Authorization-only availability does not enable orders. Synthetic HTTP/SQL tests, real PostgreSQL concurrency tests, native iOS tests, simulator compilation and an unsigned device archive cover this implementation.

Windows now provides a bounded asynchronous technical logger and a disconnected support export. Records omit exception messages, HTTP content, credentials and local variables. Support ZIPs contain only sanitized technical records and minimal build/logging metadata. Queue overflow and writer failure are visible; existing execution journals remain authoritative. Packaged checks validate public source metadata and support export without broker connections.

Packaging verification exposed a resource-basename mismatch that prevented the public build revision from loading. The resource is now packaged as `build-info.json`. Self-test failure reporting also exits without an interactive error dialog and excludes error messages. A separate regression ensures logging stack capture does not perform source-file I/O on the execution path.

One installer CI attempt timed out in an existing recovery test during its one-second reconnect wait. The test now stops at the dashboard request after batch processing, retaining its cursor, quarantine and accepted-trade assertions. Production retry behavior is unchanged. Both the failed attempt and subsequent verification are retained in the evidence.

No real orders, Discord messages, Webull deployment or secret configuration were performed for these changes. The approved Webull account/contract/order adapter and long-only source reservations still require implementation and integration acceptance. Operator activation, real sandbox consent/order testing, Apple signing and physical cross-network acceptance remain unpassed. Local technical logs do not provide independent dead-PC notification or automatic trading restart.
