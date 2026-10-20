# Direct mirroring implementation plan — 2026-10-20

Approved design: pair once, follow automatically, no Discord parsing or per-trade prompts.

Architecture: authenticated HTTPS fill messages from the native Alpaca monitor to a PC receiver. Receiver pins its Alpaca account/environment, serializes execution, commits an immutable event and deterministic order identity before network submission, and reconciles unknown outcomes without reposting. Sender retries transport with the same event identity. Receiver defaults paused; enabling Follow is standing authorization. No live broker requests during development.

Scope: standard single-leg long options and whole shares, source execution quantity, day limit at source price, no short opens. Source events expire after 60 seconds. Unknown source intent is checked against the source order; unsupported intent is skipped. No historical replay at enrollment. The native sender uses Keychain pairing and independent durable delivery state. PC console provides pairing, follow/pause, and recent results. Internet deployment requires HTTPS or private networking. iOS must remain active to observe fills. Native phone execution and Webull integration are not claimed by this increment.

- [x] Write failing receiver tests: duplicate/restart, altered replay, stale events, cross-environment, pause, unknown POST, insufficient holdings, account mismatch.
- [x] Implement crier/mirror.py with SQLite journal, pairing authentication, Alpaca adapter and serialized execution.
- [x] Add authenticated owner routes and isolated customer ingestion route in crier/mirror_routes.py; add console at /mirror.
- [x] Test route pairing, authorization and lifecycle with fake broker transport.
- [x] Add native MirrorConnection.swift with Keychain pairing, durable watermark/outbox and verified source order intent. Integrate AlpacaWorkspace refresh and pairing form, register Xcode source/test files.
- [x] Run Python suite and native CI; inspect changes; document setup and limitations; commit/push main directly as requested.

Broker reference: https://docs.alpaca.markets/us/reference/postorder and https://docs.alpaca.markets/us/reference/getorderbyclientorderid. POST uses a deterministic client_order_id; timeout is unresolved, never a fresh retry. Sell requires qty_available and explicit sell_to_close.


