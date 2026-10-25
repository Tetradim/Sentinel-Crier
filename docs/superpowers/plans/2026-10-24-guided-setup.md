# Phase F — Cross-platform guided setup

> **For agentic workers:** Use subagent-driven-development for independent platform tasks, then review integration and verification before committing directly to main.

**Goal:** Finish the approved purpose-driven setup design without changing pricing, order reconciliation, or live authorization policy.

**Baseline:** `8f62bff`. Phase F.1 already supplies Windows alerts-only monitoring with isolated credentials, cursor and outbox. Phase E controls and A–D offline server work remain intact.

**Design:** Keep a single app with Alerts, Trade/share and Follow routes. Saving a purpose only selects navigation. Account/environment verification, Discord preview, explicit test result and permission to publish remain separate evidence. Clear readiness when relevant configuration changes, disconnects or the process restarts; retained settings are reusable, not proof of a current connection. No automatic tests, connects, enables or trade submissions on first launch. A test is a labelled synthetic message; its acknowledgement never represents a fill. Do not make successful test delivery or paper practice a new mandatory live-trading gate. Inactive journey controls must not mutate another profile.

## Tasks

- [ ] F.2 Android: add purpose selection and a guided account/Discord path. Alerts-only must verify/read Alpaca without Host/Receive, relay or an order engine, use separate encrypted configuration and durable account/environment-scoped state, and preserve baseline/outbox uncertainty rules. Expose foreground/background limitations. Test setup transitions, restart, read-only HTTP boundaries and fill evidence. Keep existing Trade/Follow recovery available.
- [ ] F.3 iOS: integrate purpose-driven setup with the existing native broker/fill publisher. Show account verification, configuration/preview/test and delivery permission honestly. Alerts-only must not activate a saved mirroring engine or require a channel. Preserve journals, Keychain identity, explicit live permission and foreground lifecycle. Test readiness invalidation and no execution on the Alerts path.
- [ ] F.4 Windows: add guided preview/test/enable readiness to the F.1 path, retaining explicit controls and destination-preservation constraints. Scope evidence to active account/destination; clear stale asynchronous completions. Test incomplete setup, reconnect, destination changes and failed/uncertain test acknowledgements using mocked workers/HTTP only.
- [ ] F.5 Review each platform against the above design, fix findings, run complete Python and native compilation/test/package CI, and record source-bound evidence. Update phase status and customer instructions precisely; physical/broker/Discord acceptance stays deferred.

## Verification boundaries

Use temporary stores, synthetic credentials and injected/mock HTTP. Never place broker orders or send real Discord messages for automated acceptance. Native compilation uses available local tooling and existing CI. Signed iPhone installation, actual OAuth registrations, Webull approval and physical network tests remain separate external gates. If existing platform architecture makes a requirement substantially larger, implement a complete bounded journey and record the remaining gap instead of presenting saved preferences as implemented capability.
