# Crier Implementation Plan

> Execute inline using executing-plans. User approved the design; proceed through implementation and verification without another design approval.

**Goal:** A runnable iPhone-oriented Crier service with Homebrew-style previews and an opt-in Webull event observer.

**Architecture:** Validated broker snapshots feed a transactional SQLite ledger and outbox. A single worker sends Discord alerts. A FastAPI application serves authenticated configuration/history APIs and a responsive static interface. The Webull SDK is isolated from the renderer and never used to submit trades.

**Tech Stack:** Python 3.11, FastAPI, SQLite, httpx, official Webull SDK, semantic HTML/CSS/JavaScript, pytest.

## Tasks

- [x] 1. Write domain tests in `tests/test_core.py`: decode `SPY261016C00600000`, reject malformed/ambiguous options, reject nonpositive/nonfinite fills, derive delta 2 from cumulative 1→3, deduplicate across restarts, quarantine conflicting equal-quantity prices. Run `python -m pytest` and observe missing modules. Implement `crier/models.py`, `crier/store.py`, `crier/cards.py`.
- [x] 2. Write delivery tests in `tests/test_delivery.py`: 200 stores message ID, 429 defers using Retry-After, permanent failure stops, network ambiguity requires review. Implement `crier/delivery.py` using injected httpx transport; preserve frozen payloads and an at-most-one in-flight sender transaction.
- [x] 3. Write API tests in `tests/test_api.py`: unauthenticated requests fail, invalid settings fail, previews never enqueue delivery, saved settings survive restart, secrets absent in status. Implement `crier/app.py`, `crier/config.py`, synthetic samples, and the service entry point.
- [x] 4. Inspect installed official SDK signatures before writing `crier/webull.py`. Add adapter fixture tests and a read-only history export/reconciliation command. Keep live stream disabled unless server environment explicitly configures it; track heartbeat and errors. Document manual-app coverage verification.
- [x] 5. Build `crier/static/index.html`, `app.css`, `app.js`, manifest and icon. Add preview scenarios, editable appearance, history, connection status and session-memory authorization. Use accessible controls, safe text rendering and mobile safe-area spacing. Check JS syntax and operate in a browser at 390px and 1440px widths.
- [x] 6. Run generated entry/exit text through Echo's local parser in a separate read-only subprocess. Add a reusable compatibility check script that takes an external Echo checkout path; no runtime dependency on private Echo source.
- [x] 7. Write README, deployment files and environment example. Run the full tests, compile check, JS syntax check and diff check. Review security and reconnect behavior. Commit the isolated feature branch and create a draft PR if repository access permits; attach it to this chat.

## Validation commands

```powershell
python -m pytest -q
python -m compileall -q crier
node --check crier/static/app.js
git diff --check
```

External posting, Webull authentication, and deployed HTTPS remain explicit environment setup steps. No user keys or historical private alerts are copied to this repository.

## Implementation outcome

The user clarified this is free open-source software, not a hosted customer service. The supplied Tradier CardKit established the exact Homebrew Markdown headline/fill format; it is now the default alongside an optional rich card. 45 automated tests pass at this checkpoint. Live broker validation is external and remains outstanding. Reconciliation tooling exports one raw history page and accepts an operator-verified complete baseline; automatic history backfill, position P/L, edit-in-place and Echo exits are deliberately not represented as implemented. The generated Echo BTO entry was tested read-only against the existing parser. Browser checks cover 390px and 1440px Chromium, not an actual iPhone.
