# Windows customer readiness and startup notices

Implement the four selected customer handoff improvements: automatic update checks at startup only, clear connection state, a read-only first-run connection test, and a support/version/export dialog. No daily/periodic update check, automatic installation, order placement or Discord test posts are added. Existing manual updates remain available after banner dismissal. Hidden tray startup must remain hidden.

Architecture: a per-window startup notice coordinator gates one asynchronous check. A dismissible non-modal banner links to the existing update page. Pure readiness presentation interprets execution/relay health and unresolved orders before claiming Hosting/Following. A lifecycle-serialized diagnostic verifies the selected broker identity/environment and authenticated relay dashboard using GET only; it never advances cursors or changes execution settings. Results explicitly distinguish connectivity from untested trade/Discord delivery. Support shows public version/source/platform, opens the public support page only on request and reuses sanitized support export.

- [x] Test-first startup notice coordinator and readiness/probe helpers.
- [x] Integrate Windows startup banner, status/explanations, connection-test action and support dialog.
- [x] Verify lifecycle cancellation, no orders/messages and no network during packaged smoke tests.
- [x] Build/test/publish Windows 0.3.1 with compatible profile/protocol generation 1; record accepted source and public update verification.

Accepted runtime: `49d77cc94bce82eedf4d4f0bad074026a0cd2261`. [Evidence](../../acceptance/2026-10-27/customer-readiness/README.md).
