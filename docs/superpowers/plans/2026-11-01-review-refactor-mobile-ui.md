# Review fixes, module extraction and brokerage UI

Approved by the owner on November 1, 2026. Baseline: `660e864`.

## Implementation sequence

1. Reproduce and fix the reviewed execution defects: immutable dialog route ownership, account-wide recovery pause, OAuth return routing, monotonic iOS broker evidence, explicit host entry authorization, Android durable no-submission recovery, asynchronous bank reads and safe pool editing.
2. Extract cohesive modules from the desktop shell/runtime and native trading shells. Preserve account pinning, bank transactions, ownership, unknown-outcome protection and deliberate trading permissions. File size alone does not justify dividing a financial transaction.
3. Improve mobile trading hierarchy and Windows usability. Keep the selected account and paper/live environment visible, make positions/orders easier to find, simplify setup disclosure and preserve accessible emergency controls and exact-contract order confirmation.
4. Run focused regressions, the full Python/Tk suite, native trading tests and simulator/emulator customer journeys. Review source and actual screenshots. Publish updated installers only from the verified source and retain checksums/signature evidence.

## UI references and decisions

Official Webull [platform navigation](https://www.webull.com/help/faq/11033-General-Platform-Navigation) places the mobile account selector at the top left, positions under Account, and symbol discovery in Markets. Its [order instructions](https://www.webull.com/help/faq/291-Where-do-I-place-an-order) connect positions or symbol detail to a ticket and confirmation; open orders provide cancellation/modification.

Crier follows that account-first hierarchy, compact dark brokerage presentation, segmented trading controls and persistent navigation. Crier retains its own name, explicit connection/permission state, recovery evidence and stop controls. Unsupported or disconnected market data stays visibly unavailable. No decorative quote, balance or performance is presented as live evidence.

UI acceptance must include narrow mobile screens, larger fonts, reachable account/stop controls, disconnected empty states, scrolling and navigation back to recovery. Screenshots are captured from installed native apps; synthetic tests and simulator screenshots do not establish provider acceptance.

## Existing deferrals

The [owner-deferred physical/provider checklist](../../deferred/2026-10-31-owner-provider-acceptance.md) remains in force. Apple enrollment/signing, physical-device and real-provider acceptance are outside this implementation. No live brokerage transaction or customer notification is part of the automated verification.

## Evidence

The [accepted verification record](../../acceptance/2026-11-01/review-refactor/README.md) contains commit-specific test results, module sizes, actual native screenshots and release-artifact verification. Earlier 0.5.0 acceptance remains historical evidence rather than proof of these changes.
