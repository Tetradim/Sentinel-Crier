# Windows account ID bank — automated evidence

Scope: Windows main, several host pairings into one Alpaca destination on one receiver installation. Opt-in transition only; separate-account unmanaged routes retain existing behavior. No live money, credentials, Discord messages or broker network requests were used by the new synthetic tests.

| Scenario | Automated evidence |
| --- | --- |
| Two hosts, same option/account | Actual IntentEngine instances buy 3 + 5; first host exits only 3; second retains 5. |
| Units / dollars / equity-percentage pools | Exact Decimal allocation tests and Windows route editor/runtime integration. |
| Competing cash reservations | Concurrent transactions admit only one order when the combined amount exceeds cash. |
| API timeout / repeated invocation | Unknown order and cash reservation persist; no second POST. |
| Partial execution / cancellation | Two fills of five survive cancellation; only unfilled reservation releases. Setting pool to zero does not remove exit authority. |
| Retirement / replay | Empty terminal IDs leave active bank; retained history rejects source reuse; numeric IDs are not recycled. |
| Restart / setup migration | Bank reservations survive restart; startup stays disconnected. A working legacy order refuses shared-bank activation. |
| Stale funds / changed instruction | No POST on stale funds or final pre-dispatch supersession. |
| Wrong account / instrument / malformed proof | Binding checks and conflicting-evidence cases retain reservations and block entries. |
| Unexpected account inventory | No ownership reassignment or silent rebaseline, including when flat. Matching inventory can clear only an inventory-specific block. |
| Logging pressure | Repeated identical broker proof does not append duplicate audit rows or charge twice. |
| UI | Tk widget tests verify visible active IDs, retained fee values and explicit pool-save action without connecting or trading. |

The screenshot's +3% and −2% autonomous triggers are strategy requirements, not newly implemented strategies. Host instructions remain the source of Crier orders. This work covers their allocation, exact instrument, ownership, freshness and submission/reconciliation boundaries.

Verification commands:

```powershell
python -m pytest -q --tb=short
python -m pytest tests/test_allocation_bank.py tests/test_managed_account.py tests/test_shared_account_desktop.py tests/test_bank_broker_reads.py tests/test_account_bank_ui.py -q --tb=short
git diff --check
```

Final local full suite: **1,272 passed, 1 skipped**, with the existing Starlette/httpx deprecation warning. The focused bank/dispatch/UI group passed **38 tests**; `git diff --check` passed. No independent external review or physical broker-UI acceptance is claimed. Native shared-account receiver integration and a new published Windows installer remain separate work; unchanged native guards were intentionally preserved. Remote CI status is separate from these local results.

Read [setup and limits](../../../account-id-bank.md), [source research and design](../../../superpowers/plans/2026-10-29-id-bank.md), and [donor review](../../../reviews/2026-10-29-sentinel-allocations.md).
