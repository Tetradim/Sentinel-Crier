# Review improvements — Crier 0.5.3

The approved work was implemented in order: shared native scenarios, journey coordinators, selected diagnostic logging, then plain-language explanations.

## Implemented scope

- Seven [shared native invariant scenarios](../../../protocol/native-invariants.md) exercise real bank/clock implementations, including late cumulative fills and durable refusal of decreasing proof. Exact API/storage/lifecycle differences are documented; this is not a claim of whole-engine parity.
- DesktopJourneys separates navigation, setup and connect callbacks while retaining DesktopApp entry points and app-owned route/Stop/action-epoch fences. Android JourneyCoordinator separates purpose/route transition ordering and retains the original process-owned writers, OAuth inbox and lifecycle owners. These are focused extractions, not complete removal of every large UI/controller file.
- Optional trace/queue/clock/transport failures record fixed sanitized codes through the existing bounded logger. Failed logging remains nonfatal. Expected wait timeouts stay quiet; retry exhaustion remains thirty attempts.
- [What happened explanations](../../../decision-explanations.md) read existing records on Windows, Android and iOS. Seventy-seven shared explanation examples cover known/unknown stages, partial/terminal status, cancellation distinction, chronology and privacy. Windows clears summaries and advanced timeline text on selection/route changes and rejects late results. No permission or execution path is added.

## Local verification

- Full Python/Tk suite before the final advanced-timeline isolation fix: **1,437 passed, one optional test skipped** in 189.18 seconds. Final isolation fix and regression: **44 relevant checks passed**.
- Full Android production/test compilation against SDK35: **200 JUnit tests passed**, including the real plain-enum journal adapter regression. The existing decor-fits-system-windows deprecation warning remains.
- Independent review prompted cumulative-fill correction coverage, retry-exhaustion coverage and the Android reason-enum adapter fix. Each was verified. A moved desktop import was corrected during the coordinator self-review.
- `git diff --check` passed before source commit. Hosted checks, package acceptance, source IDs and publication receipts are recorded after their workflows finish.

Synthetic tests use no real brokerage orders, customer notifications or provider credentials. Apple signing, physical/provider acceptance and Webull activation remain owner-deferred.
