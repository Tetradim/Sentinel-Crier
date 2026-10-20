# Sentinel Crier

Free, open-source broker fill alerts and a native iPhone trading interface for the
Sentinel family. Crier publishes **executions confirmed by the broker**; submitting
an order is not a fill and does not produce a filled-trade alert.

## Two ways to run

- **Native iPhone app:** connect a personal Alpaca account directly, review and
  confirm stock or standard single-leg option day-limit orders, reconcile orders,
  view positions, and publish fills to Discord. Paper is the default. Live requires
  separate credentials, an explicit environment selection, and a real-money
  confirmation. No Python service is required for this path.
- **PC / self-hosted monitor:** keep using your normal brokerage interface while
  Crier polls supported broker fills and publishes through a durable Discord
  outbox. Its responsive console works on desktop and mobile. The Python monitor
  never places or cancels trades.

The phone monitors while Crier is active and catches up when reopened. It cannot
promise continuous background monitoring while another app is in use. Use the
optional always-on monitor for that requirement. Do not enable both publishers
for the same account and destination: their independent ledgers cannot deduplicate
one another's Discord messages.

## Broker support

| Broker | Native iPhone | PC monitor |
| --- | --- | --- |
| Alpaca | Paper/live personal API; stocks and standard long single-leg options | Authenticated paginated FILL activities; paper/live |
| Webull | Connect application pending; not connected | Experimental official SDK observer; requires validated baseline and permissions |
| Tradier | Not integrated | Read-only polling adapter; account-specific validation required |
| Other brokers | No automatic screen access | Manual reviewed receipts or authenticated observer integration |

A Webull Connect application is not approval or an active integration. Crier does
not scrape brokerage passwords, screens or notifications. Historical ReplayKit
instructions describe removed iOS code and are not current installation steps.

## iPhone setup

See [native build and operation](ios/BUILD.md) and
[device release checklist](docs/iphone-release-checklist.md).
See [native data handling](docs/native-data-handling.md) for local retention and
what is sent to Alpaca and Discord.

A simulator build is not installable on an iPhone. A signed device package requires
an Apple development team and matching signing assets. The manually triggered
**Signed iPhone package** GitHub Actions workflow exports an IPA using repository
secrets; it does not automatically publish to the App Store or submit to TestFlight.

The native workflow supports paper validation before selecting live credentials.
Start with a private test Discord webhook. On first account connection, existing
fill history is baselined silently; future broker fills are eligible for alerts.
Unknown submission outcomes must be reconciled by the saved client order ID before
placing another order. Unknown Discord outcomes are retained for manual inspection.

## PC quick start

Python 3.11 or newer:

```powershell
git clone https://github.com/Tetradim/Sentinel-Crier.git
cd Sentinel-Crier
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m crier serve
```

Open http://127.0.0.1:8765 and unlock using the private token in
`data/access-token`. The default console previews messages without posting to
Discord. On macOS/Linux activate with `source .venv/bin/activate`.

For Alpaca, follow [Alpaca monitor setup](docs/alpaca-setup.md). Configure credentials
as environment variables and select `python -m crier serve --monitor alpaca`.
`ALPACA_ENV=paper` is the default; set `live` explicitly for a real account.
The CLI reads process environment variables, not `.env` files automatically.
Docker Compose loads `.env` through its configured `env_file`.

Discord sending additionally requires `DISCORD_WEBHOOK_URL`,
`CRIER_DELIVERY_ENABLED=true`, and `CRIER_PUBLISHER_VERIFIED=true` after checking
its destination and queued records. Keep one monitor and one publisher per account
installation. Never commit API keys, webhooks, tokens or data files.

## Alerts and recovery

The PC console offers Homebrew-style Markdown, rich cards, compact plain text and
restricted Echo-compatible BTO text. Native iPhone supports Homebrew-style Markdown, plain text and cards.
Paper/live provenance and broker execution times remain visible. Unknown position
intent is not converted to a guessed opening or closing trade.

- Broker fill IDs and durable records suppress repeats after restart.
- Discord 429 responses defer retries. Ambiguous sends remain uncertain to avoid
  automatically duplicating a message that Discord might already have accepted.
- Initial Alpaca history enrollment is silent; subsequent catch-up is paginated.
- Manual receipts stay explicitly user-confirmed and cannot authorize trades.
- A sell is not necessarily a full position close. Running P/L, peak-price tracking,
  automated stops/take-profit, copied trades and multi-broker execution are not
  claimed as complete features of this release.

Details: [monitor/publisher guide](docs/monitor-publisher.md),
[Webull validation](docs/webull-validation.md),
[Tradier validation](docs/tradier-validation.md),
[server journal boundaries](docs/live-execution-architecture.md).

## Deployment and verification

`docker compose up --build -d` runs the optional monitor with a persistent volume.
Its port is localhost-only by default. Use a TLS reverse proxy for remote access,
private per-user data directories and restricted filesystem permissions.

```sh
python -m pytest -q
python -m compileall -q crier
node --check crier/static/app.js
```

Tests use local fixtures and mocked transports, not live-money orders or Discord
posts. iOS compilation and XCTest run on macOS CI. Check the exact commit's CI
results; a workflow file alone is not evidence of a successful build. Physical
phone operation, signing and App Store review are separate acceptance steps.

[Source/reuse references](docs/source-references.md). MIT license.

## Direct trade mirroring

Pair a customer's iPhone with a PC receiver to follow confirmed Alpaca fills without Discord parsing. The receiver owns its credentials and has Follow/Pause controls. Start with paper accounts. See [setup, supported orders and delivery behavior](docs/direct-mirroring.md). Phone-only execution and Webull mirroring are not implemented.
