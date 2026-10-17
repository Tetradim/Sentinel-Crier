# Alpaca paper validation — October 16, 2026 (America/Chicago)

## Scope

Direct HTTPS requests to `https://paper-api.alpaca.markets/v2` using
user-authorized paper credentials. Credentials were not saved in this repository.
This was a broker connectivity diagnostic, not an iPhone or Crier gateway
end-to-end test. No live-money endpoint was used.

## Remote results

Account authentication succeeded (HTTP 200); account ACTIVE, trading not blocked,
options trading level 3. Broker clock reported the regular market closed.

| Instrument | Buy quantity | Limit price | Exact broker readback | Duplicate rejected | Final state |
| --- | ---: | ---: | --- | --- | --- |
| AAPL | 1 share | 1.01 | Yes | HTTP 422 | Canceled, zero filled |
| AAPL | 2 shares | 1.23 | Yes | HTTP 422 | Canceled, zero filled |
| MSFT | 3 shares | 2.34 | Yes | HTTP 422 | Canceled, zero filled |
| SPY261023C00500000 | 1 contract | 0.01 | Yes | HTTP 422 | Canceled, zero filled |

All initial submissions returned HTTP 200. Each request had a unique test-prefixed
client order ID. Readback by that ID preserved symbol, side, order type,
time-in-force, quantity and limit price. Prices and quantities were compared with
Decimal, not binary floating point. The option requested and returned buy_to_open.
Cancellation returned HTTP 204 and was followed by GET confirmation of canceled
status for every test order. Only this run's orders were canceled.

## Local stress results

`tests/test_journal_stress.py` adds two bounded tests of the existing journal:

- 100 staged and confirmed orders, 1,000 unique incremental fills, delivered three
  times each using 12 worker threads. Exactly 1,000 ingestions were accepted;
  2,000 duplicates were ignored. All orders retained exact quantities and limit
  prices after closing and reopening SQLite; audit-chain verification passed.
- 100 concurrent attempts to reserve the same confirmed order using 12 worker
  threads. Exactly one reservation succeeded; audit-chain verification passed.

Full suite: **141 passed**, with one existing FastAPI/Starlette HTTP client
deprecation warning. Local stress did not send load to Alpaca.

## Not yet established

No market-session fills, sell orders, execution price accuracy, reconnect recovery,
Discord delivery, or physical-iPhone end-to-end flow were tested. The stock limit
prices were deliberately far from market; acceptance does not imply execution.
The iOS broker gateway and submission wiring remain incomplete. Paper testing does
not establish live-market execution quality or make the current app customer-ready.

Next integration stage: connect an explicitly paper-only Alpaca adapter to a
customer-confirmed order route, retain durable reservation and reconciliation, and
connect the iOS gateway. Then run a market-session paper buy/sell and verify fills
through Discord before enabling a separately configured live-money connection.

API references: [orders](https://docs.alpaca.markets/us/docs/working-with-orders),
[lookup by client ID](https://docs.alpaca.markets/us/reference/getorderbyclientorderid).
