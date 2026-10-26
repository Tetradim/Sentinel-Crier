# Phase I customer acceptance implementation plan

Execute the approved automated scope directly on main. Defer owner-dependent/physical checks without requesting them again.

- [x] Add a strict, shared read-only practice guide and parser tests; bundle it in Windows, Android and iOS.
- [x] Add guide/support entry points without connection or permission mutations. Fix Android label associations and Windows read-only text keyboard traversal.
- [x] Add fresh-customer paper Alerts and recovery acceptance using real controllers/parsers/outbox with injected HTTP; add a runner reporting observed offline durations, skips/failures and source binding.
- [x] Add Android emulator and iOS simulator UI acceptance for optional guides, accessible inputs and unchanged disconnected startup; retain all current unit/build/installer checks.
- [x] Refresh customer installation/recovery/support and real first-success measurement instructions. Keep real trials unpassed and practice optional.
- [x] Run focused/full checks and source-bound CI, collect evidence, fix findings, commit/push and report the remaining external gates without claiming full production acceptance.

## Completion evidence

Implementation `1be5162`, desktop test-isolation fix `95ceb88`, and final customer copy `150ac97` are verified. All final CI runs use `150ac97`: Windows **941/one optional SDK skip**, Linux 3.11/3.12 **908/34 expected skips each**, backend **839/36 expected skips**, **108 Android unit tests**, **124 iOS unit tests**, Android emulator UI **two tests**, and iOS simulator UI **one test traversing all three guides**. Windows packaging/installer lifecycle, Android packaging and iOS simulator/unsigned hardware archive also passed. The Windows customer runner passed six cases without skips, recording offline durations and an explicitly unmeasured real first-success result.

The initial local 22 unexpected GUI skips were rejected; a shared Tcl interpreter and fail-on-Windows-init policy corrected the test harness. The final local full suite passed **941/one optional SDK skip**. Native screenshots were reviewed and the guide intro shortened; proposed roadmap details were removed from the customer-facing Follow guide. See the [source-bound report](../../acceptance/2026-10-25/customer-acceptance/source-evidence.json).

Phase I automated source acceptance is complete. Actual customer/provider/device trials, signing/installation and assistive-technology validation remain unpassed. H.5 proposed live execution modes remain source implementation work. The [remaining-work list](../../remaining-work.md) keeps these categories separate.
