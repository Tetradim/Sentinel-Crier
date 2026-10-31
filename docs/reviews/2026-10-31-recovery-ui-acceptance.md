# Recovery and native UI acceptance status

The native simulator build and UI capture succeeded for `ed8eebe`. Four real running-app screenshots were recovered from the UI-test logs: Home, Positions, Recovery and Markets. All show a disconnected paper workspace. They are not live brokerage acceptance or design mockups. Capture run: https://github.com/Tetradim/Sentinel-Crier/actions/runs/41189397172 (the iOS job passed; a separate Android window-focus timeout failed the aggregate run and was rerun).

Inspection identified route-picker wrapping and excessive Home navigation height. The follow-up source hides the redundant picker label, gives its selection flexible single-line width and uses an inline Home title. Windows screenshot inspection also identified activity controls outside the initial viewport; the Trading tab now has a vertical scroll container. A Tk regression test checks that the scroll controls exist.

Recovery checking preserves any prior evidence block, even if inventory matches. A regression test reproduces the previous misleading verified result and verifies it remains unresolved. Route-switch refusal, visible quantity differences, unknown reservations and non-submitting checks are covered separately.

Final local Python/Tk suite for these fixes: **1,280 passed, 1 skipped** (existing Starlette/httpx deprecation warning). Focused recovery/route/UI group: **30 passed**. Native compilation and UI tests passed for the preceding screenshot source; follow-up layout source needs its own native run.

Actual screenshot files are retained locally under `work/ui-captures/ios-*-disconnected.png` and `windows-*-disconnected.png`. Screenshots are not edited to conceal layout defects. Follow-up screenshots are still needed to accept the new layout fixes, along with large Dynamic Type, landscape and physical VoiceOver/lifecycle trials.

Source scope delivered: Windows recovery guidance with owned/external/broker comparisons and safe authoritative reconciliation; iOS local recovery diagnostics plus a scoped GET-only manual-order evidence check; dark mobile workspace, positions search, segmented order ticket, exact option summary and adaptable chart controls.

This does not complete native shared-account bank parity, broker-authoritative repair of contradictory evidence, Webull execution/provider activation, Apple signing, new installer publication or physical cross-network trading tests. Those remain product work rather than implied acceptance of this UI change. Arbitrary clear/reset/resubmit actions are deliberately not a recovery mechanism.
