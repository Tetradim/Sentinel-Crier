# Phase I automated customer acceptance

Continue the approved customer-ease plan directly on main. Complete source work that does not need owner accounts, signing or physical devices. Preserve the existing live-consent behavior: paper practice remains optional and never becomes a live-submission prerequisite.

## Customer-facing changes

Bundle one static paper-practice guide for Alerts, Trade/share and Follow in all three clients. It explains account/environment verification, preview versus synthetic acknowledgement versus permission, fresh-fill baselines, submission-time mirroring, cancellation/partial fills and recovery. It contains no credentials, executable actions, completion flags or trading authorization. Reading or choosing a guide does not change purpose, connect, enable delivery or place an order.

Expose the guide from Windows Start here/F1, iOS Home, and Android setup. Return to existing setup and recovery controls rather than introduce another account workflow. Offer the approved public GitHub Issues support route with a reminder to remove credentials, invitation tokens, webhook URLs and account data. Do not create issues or upload logs automatically.

Associate Android's editable fields with their visible labels and hints using native labelFor/IDs. Keep secure input types unchanged. Make Windows read-only guide/evidence text keyboard-traversable; Escape closes the guide and its initial selector receives focus. Use native iOS navigation and accessibility identifiers for deterministic UI testing. These changes do not establish VoiceOver/TalkBack/Narrator or WCAG compliance; physical assistive-technology checks remain deferred.

## Acceptance evidence

Add offline fresh-customer journey tests through real desktop session, activity parsing, publisher/outbox and recovery code with injected HTTP transports. Assert option contract, quantity and premium transfer, explicit delivery permission, synthetic versus fill provenance, first-fill acknowledgement, restart/reconnect behavior and uncertain-message preservation. Unexpected HTTP methods/hosts fail the tests; no real broker or Discord request is authorized.

Provide a runner that records source revision, actual test outcomes and observed offline test durations. Label those durations as automated simulation time, not human setup time or cross-device latency. Real customer first-success time remains unmeasured until the deferred account/device trial; document a repeatable measurement procedure without inventing a target or passing result.

Add simulator/emulator UI checks for opening the optional guide, navigating it and returning without authorization. Android also checks editable-field label associations on the real platform. Retain the existing unit/build/installer checks. No test-only order-permission bypass or synthetic customer "passed practice" state is introduced.

## Exit boundary

Source acceptance can pass after offline journeys, native tests/UI automation, packaging and source-bound report collection. Signed iPhone installation, actual Windows sign-in, physical lifecycle/accessibility, Webull approval/activation, real broker/Discord receipts and human first-success measurements remain explicitly unpassed. Proposed H.5 sizing modes remain design-only. Refresh installation/support documentation to distinguish usable artifacts from unsigned archives and current features from proposals.
