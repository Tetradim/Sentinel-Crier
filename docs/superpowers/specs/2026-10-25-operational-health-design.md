# Operational health — Phase H.1

This implements the first slice of the owner's approved Phase H plan: durable component health and customer recovery presentation on Windows. Native mobile presentation follows in H.2; tray/startup and execution-policy work are separate later slices.

Use a small SQLite health ledger scoped to the verified environment/account and pairing. Track broker verification, fill reads, relay publishing/receiving, execution worker and Discord delivery separately. Evidence comes from existing operations; opening a screen must not add broker requests or send messages. Persist last success and a fixed, redacted reason code. A restarted process or reconnected session must verify again before saved successes appear current. Scope changes must never reuse another account's evidence.

The UI shows component, state, last successful check and one recovery hint. Stopped/disabled, waiting, idle, stale, blocked and degraded are distinct from healthy. Idle publishing means no queued work, not proof of relay reachability. Monotonic time measures freshness within a connection; wall-clock discontinuity is visible and cannot make old evidence fresh. Health status is informational and does not change order policy, authorize sending or resolve an order.

A Health tab offers existing setup/history navigation and explicit disconnect. It does not add a manual order-resolution shortcut. Broker/order journals and Discord uncertain-delivery rules remain authoritative. Diagnostics must contain neither tokens nor raw HTTP exception bodies. Failure to persist diagnostics must not interrupt broker reconciliation, and must be visible in the health panel.

Tests cover restart/reconnect, account isolation, stale and clock-change states, worker/send outcomes, destination quarantine, UI navigation, and persistent evidence. All network tests use injected transports. No deployment, real order or Discord message is needed.
