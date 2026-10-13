# One application: monitor and Discord publisher

The user confirmed on 2026-10-13 that Crier should be one bot: monitor plus Discord publisher. It must not place, cancel, size, or manage trades. People keep using the broker's ordinary application. Existing Sentinel bots may consume the resulting alerts.

## Architecture

Keep the current Python/FastAPI/SQLite application and branch. An in-process monitor supervisor runs configured read-only adapters alongside the publisher. Independent `watch` remains available for existing installations, but a single `serve` can start the selected monitor. Prevent duplicate observer processes using an OS lock. No new repository or external paid service is required.

Each adapter produces a strict cumulative `Snapshot`; the store derives incremental fills, detects duplicates and disputes, freezes the public payload, and queues delivery. Generalize the broker field and public labels without losing account/environment scoping. Preserve the Webull verification gate. Add Tradier read-only order polling with a complete first baseline, persisted checkpoints, explicit capture-only/verified states and pagination handling. Unsupported/multi-leg payloads are held, never interpreted as simple fills.

## Incoming events and receipts

Borrow the Edge/Pulse communication pattern, not its trading endpoints: strict versioned envelopes, a dedicated shared key, stable event IDs, transactional acceptance, duplicate detection, and acknowledgement states. `crier.fill.v1` accepts authenticated cumulative order observations; it is disabled without a configured ingestion key and source verification. Accepted means stored, not delivered. Return the actual ingest outcome. Request retries cannot create extra Discord jobs. Same event ID with changed content returns a conflict.

For a brokerage without a verified connection, provide a receipt inbox. Pasted text is evidence, not proof of execution. Users review explicit structured fields before queuing a user-confirmed alert. Receipt intake, editing/confirmation, rejection, deduplication and audit must persist through restart. No guessed timestamps, opening/closing intent, option years, or incomplete symbol conversion. A strict key/value receipt format may prefill fields; unsupported free text remains visible for manual entry. Non-API submissions must remain clearly labeled user-confirmed in public cards and cannot use Echo's executable BTO template.

Receipt routes (console bearer authentication):
- `POST /api/receipts` with `{text, broker, environment}` creates a pending item, deduplicated by content+scope.
- `GET /api/receipts` lists up to 100 newest items, including parsed draft and validation warnings.
- `POST /api/receipts/{id}/confirm` with `{snapshot}` atomically records the supplied valid cumulative snapshot and queues one user-confirmed alert.
- `POST /api/receipts/{id}/reject` records rejection; terminal receipts cannot be republished.
- `GET /api/capabilities` describes implemented, experimental and manual capture methods. Robinhood is manual receipt capture, not verified automated native-app monitoring.

## Console

Extend the mobile-friendly console with Capture inbox and clear source status. Provide a sample receipt, review form, explicit Queue alert action, rejection, and status feedback. Never send on paste, preview, or sample selection. Show capture method, test/production environment, and delivery mode. Preserve existing studio/activity workflows. Local preview can queue confirmed items, but no Discord HTTP requests occur until delivery is enabled.

## Platform limits

An ordinary iOS app cannot silently inspect another app's private storage or subscribe to its push notifications. Supported account connections observe fills independently of the trading UI. Receipt capture is a functional fallback, not an automatic screen watcher. Robinhood documents external-agent account/order-history tools, but their coverage of ordinary brokerage accounts has not been verified. Neither proprietary code nor private logs from reference products are available merely because the user permits research.

## Verification

Exercise the full synthetic receipt/event -> durable outbox -> fake Discord pipeline; auth, replay, identity conflict, invalid input, restart, provenance and Echo restrictions. Test Tradier first-baseline suppression and subsequent incremental fills, malformed data, pagination and network errors with fake HTTP. Run existing regression suite, desktop/mobile browser checks, package build and compile checks. Live Webull/Tradier coverage remains unverified without account evidence. No tests place orders or send real Discord messages.

## Scope of this implementation

This delivers the unified monitor/publisher foundation, authenticated event intake, supported Tradier adapter, and manual receipt fallback. It does not claim all features of every researched commercial bot. Position-level P&L, OCR, native notification capture, additional broker connections, multi-destination routing and third-party execution remain separately tracked enhancements; unavailable sources are not simulated as supported integrations.
