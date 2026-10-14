# Webull screen-observation integration (experimental)

The native iOS ReplayKit extension can submit **structured OCR candidates** to Crier. It does not submit screenshots, OCR transcripts, Webull passwords or account balances. It does **not** publish Discord alerts from OCR.

## Server

Generate a random, independent upload secret (at least 32 characters) and set `CRIER_SCREEN_UPLOAD_KEY` on the Crier server. Do not reuse `CRIER_ACCESS_TOKEN`, `CRIER_INTAKE_KEY`, or the Discord webhook. Use HTTPS with a valid certificate. Restart the backend after changing environment variables.

- `POST /api/screen-observations`: accepts `crier.screen-observation.v1` JSON with `Authorization: Bearer <CRIER_SCREEN_UPLOAD_KEY>`. Disabled (503) unless the dedicated key is configured.
- `GET /api/screen-observations`: available only to the regular authenticated Crier operator, for manual inspection.
- Accepted evidence is stored as `pending_review` in SQLite. Repeating the same evidence ID with the same content is idempotent; conflicting content returns 409.
- **No OCR observation is passed to `/api/intake/fills` or the Discord outbox.** A broker-confirmed source or explicit review is still necessary before publication.

## iOS configuration

The app and ReplayKit extension must be signed with an Apple team that provisions:

1. App Group `group.com.tetradim.sentinelcrier` for both targets.
2. Shared Keychain group `<TeamPrefix>com.tetradim.sentinelcrier.shared` for both targets.
3. A separate app-only Keychain group `<TeamPrefix>com.tetradim.sentinelcrier` for the containing app.

The app's main Crier access token remains in the app-only Keychain group. The screen-upload token is saved in the shared Keychain group; the server URL is saved in App Group defaults. The extension never reads the main access token.

In the app, enter the server HTTPS URL, verify the admin connection, then enter the dedicated screen upload token and select **Enable secure screen upload**. Start ReplayKit screen broadcasting explicitly. The extension attempts to upload recognized Webull candidates and retries queued evidence when subsequent frames arrive.

**Caveats:** The local queue holds at most 100 observations; oldest records can be discarded during a long outage. Retry is best-effort and requires the broadcast extension to run again. There is no guarantee of delivery while the extension is stopped. The app currently cannot inspect the extension's queue or upload state. An observation ID is not an execution ID; identical trades require broker-side reconciliation.

## Security and deployment notes

Do not distribute a signed customer build before validating App Group/Keychain entitlements on a real device. The XcodeGen project and GitHub Actions build/test workflows are provided, but macOS compilation, provisioning, ReplayKit broadcasting and device Keychain access still require verification. Simulator tests cannot establish cross-app screen-capture behavior.

The Webull OCR parser is deliberately strict and still needs actual **redacted Webull iOS confirmation examples**. API-confirmed fills remain the preferred basis for unattended alerts.
