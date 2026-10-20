# Sentinel intent protocol v1

User-approved behavior: place trades inside Crier; publish intent concurrently with local submission, never wait for fill. iOS/Android/PC may host/follow. Modify/cancel/exit refer to the same trade_id. Broker confirmations reconcile actual local holdings. No live orders during development.

## Relay HTTP contract
All authenticated endpoints use Authorization: Bearer TOKEN. Owner uses existing Crier access token to POST /api/sync/channels {name,environment} -> {id,host_token,follower_token,environment}. Tokens have separate publish/read scopes; broker credentials never reach relay. Both apps paste JSON {url,token,environment,role:"host"|"follower"}; HTTPS required except localhost PC development. POST /api/sync/events (host token) stores immutable event atomically and returns {cursor}. GET /api/sync/events?after=0&wait=20 (follower token) returns {events:[{cursor,event}],cursor}. It is long polling: return immediately on new events, no fixed polling latency. Delivery ack/cursor is internal only. GET is replayable; followers commit event locally before advancing cursor. POST /api/sync/revoke/{id} owner revokes channel. Host never consumes follower token. A channel has one host and multiple follower devices, each with its own local cursor.

## Event JSON
Fields are exactly: version=1, event_id (canonical UUID), trade_id (canonical UUID), sequence (positive integer monotonic per trade), action (enter|replace|cancel|exit), environment (paper|live), symbol (canonical OCC or stock), asset (option|stock), quantity (whole positive <=1000), limit_price (positive decimal STRING), created_at (UTC ISO8601), expires_at (UTC ISO8601, enter/replace TTL <=30 seconds). All actions carry a complete symbol/quantity/price identity. IDs and event payloads immutable across retries. Host journals sequence and outgoing event before network sends. Do NOT publish from fill polling. Do not re-publish received instructions.

## Follower execution
Durably store every event before broker work. Highest sequence wins; cancel/exit establish permanent entry invalidation even if arriving before enter or after expiry. Never replay old enter after later revision. Expired enter/replace skipped. Every trade owns only orders it submitted; do not sell unrelated account holdings. Persist unknown before every broker mutation; ambiguous submission reconciles by deterministic client_order_id, never blind POST retry. Serial worker plus independently stored incoming invalidations. Check newest desired revision immediately before submit. Account/environment pinned. Broker reject/host reject should emit cancel. On exit, cancel working entry, wait for broker-terminal confirmation, recompute cumulative filled minus exited, then sell min(requested quantity, owned position, available holdings). No short opens. Cancel by itself cancels pending order remainder; filled holdings require exit. Replace safely cancels/reconciles old entry first and sends only outstanding target quantity with a new deterministic client ID.

## Pricing preferences (local receiver)
mode=exact_limit|market|bounded_limit. max_slippage_bps default100 (1%); max_slippage_amount default0.02. exact uses source limit. market explicitly enabled; no limit. bounded uses source limit +/- min(source*bps/10000,absolute_amount), conservatively rounds buy DOWN/sell UP to valid decimal tick. No quote is required: this is a marketable-intended bounded limit, never a promise it crosses market. max_age_seconds default10 <=30. Each follower can set max_quantity default1000; reject excess rather than silently resize. Pause skips new entries but continues cancel/exit for tracked trades. No per-trade prompts once Follow enabled.

## Files / ownership
Root: Python relay, Python intent engine, PC UI, Python tests and protocol docs.
iOS implementer: ios/** Swift intent sender/receiver, order UI modify/cancel/exit association, tests and project.yml.
Android implementer: android/** standalone Kotlin app host/follower execution, durable journal and Android Keystore credentials, build/tests workflow .github/workflows/android-build.yml.
Independent reviewer: protocol and Python safety tests/review (no production edits unless coordinated).

Implement all platforms with this wire contract. Existing fill mirroring remains legacy only and must not run simultaneously for new intent pairings. Existing Discord fills remain unaffected. No installed/signed/live claims without actual evidence.

## Broker client IDs

All platforms use `si-` + canonical event_id + `-b` for an entry/replacement buy, or `-s` + zero-based sell ordinal for an exit. The ordinal counts prior sell attempts for that same event. IDs must not contain a random device prefix. The broker scopes IDs to its account; sharing the same event ID across platforms prevents an independent second order when the same account is accidentally followed on two devices. HTTP 422 may be a duplicate-client-ID response: reconcile the saved ID rather than declaring rejection or retrying a POST.
