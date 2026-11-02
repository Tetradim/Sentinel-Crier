# Shared native invariants

`tests/fixtures/native-invariants.json` version 1 supplies the same ordered inputs
and expected outcomes to real implementations on all three platforms. These are
selected clock and account-bank semantics, **not full bank, journal, execution,
or lifecycle parity**. The consumers adapt API shapes; they do not calculate an
independent allocation or reconciliation result.

| Fixture case | Invariant asserted on Python, Kotlin, and Swift |
| --- | --- |
| `inclusive-positive-boundary-and-high-water` | A +5000 ms wall/monotonic difference is accepted; effective time retains its high-water value through smaller valid readings and advances when monotonic time catches up. Raw wall time remains separately available. |
| `negative-boundary-and-recovery` | A -5000 ms difference is accepted; -5001 ms is refused; a later continuous sample succeeds on the same clock. |
| `positive-discontinuity-and-monotonic-rollback` | +5001 ms and monotonic time before the original anchor are refused; neither refusal poisons a later valid read. |
| `shared-cash-and-account-isolation` | An unknown reservation debits common account cash and survives reopening storage; another route cannot overreserve that cash or allocate the same event again; an independent account can reserve the same source identities without modifying the first account. |
| `partial-cancel-owned-exit-and-tombstone` | A partial fill with pending cancellation retains the original cash reservation. Terminal cancellation releases only the unfilled amount; repeated proof is cash-idempotent. Another route cannot sell the lot, and a pending exit prevents overselling. A full exit releases basis, archives the active lot, and retains orders and non-reopenable identity after restart. |
| `inventory-mismatch-never-adopts-external-holdings` | Inventory differing from the setup baseline blocks entries durably without creating an owned lot. Matching inventory clears that inventory-only block and permits a new reservation. |
| `late-cumulative-fill-growth-and-decreasing-proof-refusal` | A canceled order can grow from two to three cumulative fills at the reserved price, debiting another `10` while preserving its original route/trade ownership and blocking entries. A later decreasing cumulative proof is refused, retaining three fills, the canceled status, `70` available cash, and historical ownership. Restart and matching inventory do not clear the evidence block or transfer the lot to another route. |

Bank scenarios use synthetic paper accounts, stock `SPY`, price `10`, a zero fee,
and a `100` cash/equity/pool ceiling. Assertions check available money numerically,
active-lot and retained-order counts, block presence, and cumulative fill/status
after each observation. Every observed order is also resolved through its stored
bank ID to verify that the original route/trade still owns it. `expected_filled`
specifies the retained cumulative fill after refused decreasing evidence; other
observations expect the supplied `filled` value. Refused actions must leave those expected snapshots
intact. The tests neither submit broker orders nor contact a service.

| Platform | Consumer | Production implementation | Fixture wiring |
| --- | --- | --- | --- |
| Python | `tests/test_native_invariants.py` (one pytest example per scenario) | `crier.entry_clock.EntryClock`, `crier.allocation_bank.AccountBank` | Reads `tests/fixtures/native-invariants.json` directly. |
| Android/JVM | `NativeInvariantsTest` (clock and bank test methods iterate every scenario) | `EntryClock`, `AccountBank` | Existing `android/app/build.gradle.kts` test resource directory includes all of `tests/fixtures`; no duplicate fixture copy. |
| iOS | `NativeInvariantsTests` (clock and bank test methods iterate every scenario) | `EntryClock`, `AccountIDBank` | `ios/project.yml` includes the test source and shared JSON as a `TradingTests` bundle resource. |

## Intentional adapter and lifecycle/storage differences

* Fixture clock units are integer milliseconds. Python and Swift accept seconds;
  Kotlin uses `Instant` and monotonic milliseconds. Python refuses uncertainty
  with `ClockUncertain`; native clocks return no reading. Nonfinite/overflow
  representations and entry-engine waiting/exit behavior remain platform tests.
* Python stores account-bank state in SQLite with transactions. Android uses
  locked, synced JSON and atomic replacement; iOS uses locked, protected JSON
  and atomic replacement under `@MainActor`. Reopening a bank tests durable
  state visibility, not app termination, lock contention, encrypted-vault unlock,
  mobile suspension, or power-loss durability.
* Native `enable` receives the external inventory baseline. Python establishes
  it with an initial `inventory` call immediately after `enable`. Every consumer
  starts with an explicitly empty baseline before the scenario begins.
* Account scope encodings, account-bank client-ID derivation, error text, schema,
  and audit representation differ. Consumers ask their real implementation to
  derive client IDs and bind broker proofs to those IDs. This fixture asserts
  semantic isolation, not identical IDs or serialized bytes. Android represents
  the inventory block with explanatory text; Python/iOS use a reason code, so
  shared assertions compare block presence.
* Python can return an identical existing reservation; native reserve APIs
  reject an already reserved client ID. The shared duplicate scenario instead
  tests allocation of the same event to a different route. Android also imposes
  account-wide trade ownership across routes; this fixture does not claim
  general cross-route trade-ID policy parity.
* After refused decreasing evidence, Python/iOS replace the late-fill block with
  `broker_evidence_conflict`; Android retains its earlier late-terminal-fill
  block. The shared invariant is that evidence remains blocked and original
  ownership/fills/cash remain intact. The fixture deliberately ends blocked with
  holdings; it does not claim that matching inventory authorizes recovery or
  that repair is uniform across implementations.
* Local not-submitted status names, repair admission/freshness checks, other broker
  evidence conflicts, late fills producing cash deficits, fee/PnL rounding, options, route
  registration, legacy-journal migration, and dispatch leases are outside this
  fixture's coverage. Their platform-specific tests remain authoritative.

Run Python with `python -m pytest tests/test_native_invariants.py -q`, Android
with `gradle :app:testDebugUnitTest --tests com.sentinel.crier.NativeInvariantsTest`
from `android`, and iOS with the generated `TradingTests` scheme on a supported
simulator. Swift execution requires macOS/Xcode; a Windows source review cannot
establish that its consumer compiles or passes.
