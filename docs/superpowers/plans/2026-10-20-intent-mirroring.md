# Submission-time mirroring implementation plan

Goal: implement the approved submission/modify/cancel/exit mirroring design across iOS, Android and PC.
Architecture: broker-free durable relay with separate host/follower credentials and immediate long-poll delivery; independent local executors use the v1 contract in docs/protocol/intent-v1.md.
Tech stack: FastAPI/SQLite/Python PC; SwiftUI/Keychain iOS; Kotlin Android/Keystore.

- [ ] Root: test relay scoped auth, immutable replay, sequence conflicts and cancellation tombstones; implement relay and wire into app.
- [ ] Root: test/implement durable PC executor, exact/market/bounded preferences, partial-entry exit/cancel, unknown mutation and replace reconciliation; add PC host/receiver UI.
- [ ] iOS implementer: use v1 host journal before concurrent broker/relay submit; follower long-poll worker and broker reconciliation; order edit/cancel/exit UI and XCTest; disable fill-driven mirroring for intent pairings.
- [ ] Android implementer: build standalone Android app with same v1 host/follower behavior, credentials kept locally, foreground-service receiving, durable journal; native build/tests.
- [ ] Spec review and code review: compare each implementation with protocol and user requirements; repair unsafe gaps.
- [ ] Verification: run offline tests and platform CI, document device/network/signing gates, commit/push main directly, no live trades.
