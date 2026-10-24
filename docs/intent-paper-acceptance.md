# Cross-device paper acceptance

October 24 status: the owner deferred Apple signing/enrollment and every owner-dependent Phase 4 item, authorizing Phase 5 automated work. The physical tests below remain deferred. Automated local/hosted transport checks and simulated broker integration evidence are tracked separately in [Phase 5 automated acceptance](superpowers/plans/2026-10-24-phase5-automated-acceptance.md); they do not establish that these physical/paper steps passed.

Use separate Alpaca **paper** accounts for host and follower, a paper relay channel,
and a currently tradable contract selected from the broker. Do not reuse an expired
example symbol from documentation. Start with one contract and exact-limit pricing.
Record app versions, device models, network type and timestamps without recording keys
or pairing tokens. These checks require actual devices and have not been run by CI.

## Installation and pairing

1. Follow [intent-mirroring.md](intent-mirroring.md) to run the HTTPS relay and pair
   one host and one follower. Keep iOS in the foreground. Start Android's sync service.
2. Verify both apps show the intended paper account and selected role. Enable following.
3. Keep both broker dashboards available to independently inspect order IDs, symbols,
   quantities, limit prices, status and cumulative filled quantity.

## Order correctness and latency

1. Submit one host limit buy at a price unlikely to fill immediately. Verify the
   follower receives the same complete OCC symbol and quantity and creates its order
   while the host order is still unfilled. Do not infer delivery from Discord.
2. Compare host submission time, relay receipt time and both broker order creation
   times. Record the measured delay; no fixed latency or matching-fill promise applies.
3. Replace the host order's limit. Verify the previous order becomes terminal before
   a replacement opens, and previously filled quantity is subtracted from the target.
4. Cancel it. Both broker dashboards must show no remaining working buy for that trade.
   Any racing fills remain owned positions; cancellation does not sell them.
5. For a filled paper entry, request Exit. Confirm sell-to-close, the exact contract,
   and quantity no greater than that trade's acquired holdings. Compare actual fills
   and remaining holdings on each account independently.
6. Repeat with bounded-limit pricing and verify the follower limit stays within both
   configured allowances. Test market pricing only after explicitly selecting it.

## Interrupted delivery and recovery

- Disconnect the follower network, enter and cancel on the host, then reconnect.
  The canceled entry must not open a new position.
- Pause following, send an entry, then resume. The entry received while paused must
  not execute later. Cancel/exit controls for already tracked trades remain active.
- Restart each app after an order exists. Confirm recovery finds the same broker
  order by client ID and does not submit it again.
- Revoke the channel and verify transport stops. Inspect broker orders separately:
  revocation is not an order cancellation.
- If an order response is ambiguous, confirm the app reports reconciliation rather
  than generating a fresh order. Resolve its broker status before further testing.

Run host/follower pairs iOS→PC, PC→Android, Android→iOS, then reverse each direction.
Keep an evidence table with expected/actual symbols, quantities, prices and order IDs.
Any unexpected position, duplicate, stale entry or incorrect quantity fails acceptance.
Stop new entries and inspect the brokerage dashboards before resuming.

CI covers simulated partial fills, response loss, replay and sequencing. A paper broker
may not reproduce partial fills or network ambiguity reliably; passing paper checks
does not establish live-market slippage or execution quality.
