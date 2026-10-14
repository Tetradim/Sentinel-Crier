# Stages 2–4: implementation review and handoff

Date: 2026-10-14

## Stage 2 — Customer experience

Implemented: five-tab dark SwiftUI command center; backend status, delivery history and observation review feed; server-backed settings; synthetic server-rendered message preview; connection setup and ReplayKit picker; actionable disconnected state; refresh on app activation and pull-to-refresh.

Review notes: UI code is uncompiled in this environment. The dashboard's record counts are limited to fetched history (100 items), not authoritative daily totals. There is no signed device build. Broadcast activity is deliberately labeled unverified rather than displaying a false green connected badge. Rich-card preview shows title/description, not a pixel-exact Discord embed.

## Stage 3 — Reliability and safety

Implemented in repository: persistent SQLite outbox and idempotent fill intake; Discord 429 backoff and uncertain-send quarantine; independent screen-upload token; bounded on-device observation queue; ReplayKit pause/resume hooks; continuous-screen observation coalescing; upload disable/purge; timestamp validation; tests for authorization separation, replay idempotence, and no OCR-driven Discord publishing.

Open issues: no reliable broker-confirmed Webull execution source for the iPhone screen pipeline; ReplayKit and Keychain behavior untested on device; observation queue only retries while broadcasting; pruning can discard old observations; an in-flight upload may finish after a local disable; no automatic historical backfill. These cannot be described as verified reliability.

## Stage 4 — Build, tests, installation

Implemented: XcodeGen project for app + broadcast extension + recognition tests, macOS GitHub Actions simulator build/test workflow, backend pytest cases, Windows backend commands, device-signing/TestFlight checklist in `docs/iphone-release-checklist.md`.

Open release blockers: no confirmed passing Xcode build, XCTest, or current backend pytest run; no Apple-signed distributable; no real-device validation; broker event coverage unverified. Do not distribute to customers or label the bot production-ready until these gates pass.

## Security and correctness decisions

- OCR observations are **pending review only**; they cannot call the verified-fill Discord intake.
- An enabled webhook is not evidence that a delivery occurred.
- A configured upload key is not evidence that ReplayKit broadcasting is running.
- Only authenticated backend data is shown as delivery history; synthetic previews are clearly labeled.
- Webull trading credentials are not requested by the iOS companion.

## Final code review disposition

**Feature implementation: advanced, with unresolved verification gates.** The repository now contains the intended UI and supporting infrastructure, but no claim is made that the complete bot is installed, running or fully automatic. Before using the nearby physical iPhone, first obtain a passing macOS build and a signed development or TestFlight build. Refer to the linked release checklist for acceptance criteria.
