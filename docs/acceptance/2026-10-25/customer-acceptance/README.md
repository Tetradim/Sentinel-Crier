# Phase I automated customer acceptance

Final application/content source `150ac97` passed the customer workflow, native builds/tests, Windows installer checks and the Python matrix. The [source-bound report](source-evidence.json) records all six successful CI runs, their exact revisions, test totals, remote UI artifacts and preserved byte checksums.

## Delivered

- One optional static guide for Alerts, Trade/share and Follow, bundled in all three clients. Reading a guide performs no account/order/publishing action and creates no completion gate.
- Windows Start here/F1, support access and keyboard traversal for read-only guide/evidence text; Android native editable-field label/hint associations; iOS Home navigation with accessible step groups.
- Fresh-customer flows through real desktop sessions, parsing and outbox code with intercepted HTTP. Checks compare complete option symbol, readable contract/expiry, buy/sell quantities and premiums, synthetic versus actual-fill evidence, explicit publishing permission, reconnect without duplicates and uncertainty preservation.
- A repeatable runner that records actual offline test-case durations and labels real customer first-success timing as **not measured**. Missing required cases, failures and skips are not treated as completed customer acceptance.
- Updated installation, recovery, support and real-trial instructions, including mobile foreground/session requirements and unsigned-iPhone-archive limits.

## Verified results

| Check | Result |
| --- | --- |
| Final Windows Python matrix | 941 passed; one optional SDK skip |
| Linux Python 3.11 / 3.12 matrix | 908 passed; 34 expected headless/optional skips each |
| Default Linux backend environment | 839 passed; 36 expected skips |
| Focused new Python checks | 19 passed |
| Windows acceptance runner | Six passed; zero skips; source clean and bound to `150ac97` |
| Android unit tests/debug package | 108 passed; packaged |
| Android emulator UI | Two passed; all three guides, native label/hint associations; font scale configured at 1.3 |
| iOS unit tests | 124 passed |
| iOS simulator UI | One test traversed all three guides, captured screenshots and returned Home without connecting |
| iOS compilation/hardware archive | Simulator and unsigned archive passed; archive is not an installable signed package |
| Windows release | 872 passed/three optional skips, packaged smoke and actual install/upgrade/downgrade rejection/uninstall with journal preservation |

The initial local full run had 22 unexpected desktop GUI skips and was not accepted. Test-only fix `95ceb88` uses one Tcl interpreter, clears stale test timers and fails Windows initialization errors instead of hiding them as skips. The subsequent local full run passed **941/one optional SDK skip**, and final CI repeated the full suite on `150ac97`. The fix changes no application source.

## Evidence and limits

- [Windows journey report and scoped offline durations](windows-journey-report.json)
- [Windows installer acceptance](windows-installer-acceptance.json)
- [Unsigned iOS archive validation](ios-unsigned-archive-validation.json)
- [Representative Alerts guide screenshot](ios-practice-alerts.png), extracted unchanged from the final simulator result bundle. Other guide captures remain in the CI result-bundle artifact. These are point-in-time captures, not full-page visual or accessibility certification.

No real broker order, Discord message, service deployment, signing or physical acceptance occurred. Actual customer first-success time remains unmeasured. Provider approval/activation, signed iPhone installation, physical lifecycle/accessibility and real cross-network broker/Discord trials remain unpassed. H.5 live sizing/notional/exit/timer proposals remain design-only. See [remaining work](../../../remaining-work.md).
