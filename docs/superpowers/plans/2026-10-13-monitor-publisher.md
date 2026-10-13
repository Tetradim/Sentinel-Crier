# Unified Monitor Publisher Implementation Plan

> For agentic workers: use subagent-driven-development for isolated tasks and review, with test-first implementation. All work stays in the existing feature checkout; do not change Edge or Pulse.

**Goal:** One application monitors brokerage fills and publishes Discord alerts, with authenticated integration intake and user-confirmed receipt fallback.

**Architecture:** Existing Snapshot -> SQLite -> frozen Discord outbox. Add versioned event intake and a receipt queue, preserving transactionality. Start one configured read-only observer with the console while retaining the standalone watcher.

**Tech stack:** Python 3.11, FastAPI, Pydantic, SQLite, httpx, vanilla browser UI, pytest, Playwright.

## Task 1: generalized events and persistence

Files: `crier/models.py`, `crier/cards.py`, `crier/store.py`, new `crier/intake.py`, `tests/test_intake.py`.

- [x] Add failing tests for multi-broker labels, strict provenance, same-event retry and content conflict, receipt restart/confirmation/rejection, and no Echo output for user-confirmed receipts.
- [x] Extend Snapshot with constrained broker slug and `verification` enum (`broker_reported`, `user_confirmed`). Canonicalize OCC whitespace before dedupe. Add provenance to the existing order identity, keeping legacy identities compatible.
- [x] Refactor ingest so an existing SQLite transaction can atomically accept an intake record and create the outbox job. Public APIs retain existing behavior.
- [x] Create `IncomingFill` (`contract_version='crier.fill.v1'`, stable `event_id`, `snapshot`). Intake store persists content hash+receipt; duplicates return original acknowledgement, changed body returns conflict.
- [x] Implement receipt persistence with strict key/value draft extraction, warnings, operator confirmation and rejection. All human receipt confirmations force user_confirmed; invalid/ambiguous input stays pending. No free-text command execution.
- [x] Run `../../work/venv/Scripts/python.exe -m pytest tests/test_intake.py tests/test_core.py -q` until green.

## Task 2: Tradier adapter

Files: new `crier/tradier.py`, `tests/test_tradier.py`, `docs/tradier-validation.md`.

- [x] Read official Tradier order documentation. Write failing fake-HTTP tests covering complete first baseline, subsequent partial/full quantities, reconnect history, multi-leg rejection and failure without advancing readiness.
- [x] Implement strict `normalize(payload, account, environment='sandbox') -> Snapshot | None`; use option_symbol for options and exec_quantity/avg_fill_price. Map explicit option side to OPEN/CLOSE. Never place/cancel orders.
- [x] Implement `poll_once(store, client, account, environment, verified=False)` using fixed official host, credentials owned by client. Persist baseline after complete response validation; retry safely after failures. Actual event ingestion uses Store.ingest.
- [x] Implement blocking `observe(config)` reading `TRADIER_ACCESS_TOKEN`, `TRADIER_ACCOUNT_ID`, `TRADIER_ENV`, `CRIER_TRADIER_VERIFIED`; acquire monitor lock and update connection state. No credentials or response bodies in console logs.
- [x] Run `../../work/venv/Scripts/python.exe -m pytest tests/test_tradier.py -q`.

## Task 3: API and single-process lifecycle

Files: `crier/config.py`, `crier/app.py`, `crier/__main__.py`, `crier/webull.py`, new `crier/monitors.py`, `tests/test_intake_api.py`.

- [x] Write failing tests for disabled intake, dedicated-key authentication, version rejection, idempotency conflicts, protected receipt endpoints, explicit confirmation and source capability metadata.
- [x] Add configuration for ingestion key/verification, selected monitor (none/webull/tradier), and independent publisher verification. Preserve existing Webull setup compatibility.
- [x] Mount receipt and fill-event routes and publish JSON schema on an authenticated discovery endpoint. Mask model-validation input values so keys/raw private receipts do not appear in errors.
- [x] Launch selected adapter in a supervised child process from serve, stop/join on shutdown, publish liveness status, prevent duplicate observer ownership. Existing watch selects configured broker with Webull compatibility default.
- [x] Run API and full regression tests; verify no outgoing order methods or new finance execution code.

## Task 4: mobile receipt inbox

Files: `crier/static/index.html`, `crier/static/app.js`, `crier/static/app.css`, new `scripts/check_capture_ui.py`.

- [x] Extend navigation with Capture inbox. Build paste form, sample receipt button, pending cards and review fields. Use textContent, no HTML injection; clear private state when locking.
- [x] Wire the exact receipt endpoints from the spec. Explicit Queue alert confirms snapshot; duplicate submit cannot create duplicate jobs. Render warnings and environment/provenance clearly.
- [x] Present broker capability cards and unified monitor health on Connections. Avoid implying automatic Robinhood capture.
- [x] Browser test at 390px and 1440px: intake sample, review, confirm, activity, duplicate prevention, reject and lock. Use local synthetic data; no credentials or Discord posting.

## Task 5: integration and release

Files: README.md, .env.example, compose.yaml, docs/source-references.md and screenshots.

- [x] Explain actual capabilities, source licenses/reuse boundaries, receipt grammar, trusted event schema and single-command setup. Keep unsupported or unverified integrations explicit.
- [x] Review spec compliance and code quality; fix material findings and add regression tests.
- [x] Full pytest, Python compile, JS syntax, browser checks, wheel build, git diff checks. Update source archive and commit/push directly to main after verification, per the user's final instruction; no PR.


## Verification record — 2026-10-13

- 101 pytest tests passed; one existing upstream Starlette HTTPX deprecation warning.
- Real Chromium studio and receipt workflows passed at 390px and 1440px, against isolated local preview servers. Synthetic status checks cover external watcher/environment labels.
- Synthetic BTO text still parses through Sentinel Echo. No execution/sizing claim.
- Python compilation, JavaScript syntax, diff whitespace and wheel build passed.
- Review findings fixed: retry of disputed in-flight jobs; loss of unsupported Tradier capture evidence; omitted contract version; missing source scope in UI. Added regression tests for atomic retries and full receipt-to-fake-Discord delivery.
- No real broker account coverage, Discord posting, iOS Safari or Docker deployment was exercised.
- User requested direct commit/push to main, with no PR. This supersedes the earlier draft-PR workflow.
