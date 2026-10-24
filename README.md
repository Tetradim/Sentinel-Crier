# Sentinel Crier

**Broker-confirmed fill alerts, local trading clients, and optional cross-device order mirroring.**

Sentinel Crier is an open-source project with three distinct workflows:

1. **Fill monitoring and Discord alerts.** A Python monitor observes supported broker execution records, journals them locally, and can send Discord notifications. An order submission is **not** a fill.
2. **Local trading clients.** Native iPhone, Android, and Windows clients support Alpaca order entry and local account management, with platform-specific setup and background limitations.
3. **Submission-time intent mirroring.** A host publishes a trade instruction when an order is created *inside Crier*. Paired followers may independently submit matching orders to **their own** Alpaca accounts after explicitly enabling execution. This is separate from fill alerts and from the older fill-based mirror.

> **Trading risk:** Mirroring can place real orders. Start with separate **paper** accounts, verify the account and environment on every device, and keep execution paused until ready. A pause, disconnect, relay revocation, or cancel *request* does not guarantee that a broker order is canceled or a position closed. Inspect unresolved orders directly with your broker. This project is not a guarantee of execution, identical fills, or investment outcomes.

## What works today

| Capability | Current scope |
| --- | --- |
| Alpaca native trading | Personal paper/live Trading API; whole shares and standard long single-leg options |
| Alpaca PC fill monitor | Read-only authenticated, paginated fill activities |
| Discord alerts | Confirmed fills via durable local outbox; delivery requires explicit configuration |
| Submission-time mirroring | iOS, Android, Windows, and Python intent device/relay; followers execute with their own Alpaca credentials |
| Remote Host / Receive | Expiring, single-use invitations via an operator-deployed HTTPS connection service |
| Execution diagnostics | Windows/iOS/Android timelines and JSON/CSV export; automatic near-event Alpaca quotes and clock-corrected delivery estimates on receivers ([setup and limits](docs/execution-diagnostics.md)) |
| Legacy fill-based mirroring | Separate optional iPhone-to-PC flow; **not** the submission-time protocol |
| Webull | [Connect approval pending; authorization-session groundwork only](docs/webull-connect.md). PC SDK observer experimental and requires validation |
| Tradier | Read-only PC polling adapter; account-specific validation required |

**Not implemented or not guaranteed:** Webull order execution, multi-leg strategy copying, guaranteed continuous iOS background operation, automatic position-level P/L or protective stops, and identical fills across accounts. A submitted order may be rejected, partially filled, or remain open.

## Choose your setup

### A. Monitor fills and send Discord alerts (Python)

Requires Python **3.11+**:

```powershell
git clone https://github.com/Tetradim/Sentinel-Crier.git
cd Sentinel-Crier
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m crier serve
```

On macOS/Linux, activate with `source .venv/bin/activate`. Open `http://127.0.0.1:8765` and unlock using the token generated in `data/access-token`. By default, the console is in **preview mode** and does not send Discord messages.

To monitor Alpaca fills, configure its account credentials and run `python -m crier serve --monitor alpaca` as described in [Alpaca setup](docs/alpaca-setup.md). To enable Discord delivery, set `DISCORD_WEBHOOK_URL`, `CRIER_DELIVERY_ENABLED=true`, and `CRIER_PUBLISHER_VERIFIED=true` **after** reviewing the destination and pending records. See the [monitor/publisher guide](docs/monitor-publisher.md).

**Execution boundary:** The normal Python *fill monitor* is read-only. The same Python application also contains an **optional, separately configured intent device** that *can place and cancel Alpaca orders* when intent broker credentials, pairing, and execution settings are provided. Do not treat the entire Python service as inherently read-only.

### B. Use a native trading client

- **iPhone:** [Build and operate the iOS app](ios/BUILD.md). Device installation requires Apple signing; simulator builds are not installable on a phone.
- **Android:** [Android setup](android/README.md). A debug APK is for testing, not a Play Store release.
- **Windows:** [Desktop application](desktop/README.md). The portable executable can run without a separate Python installation; it uses the Windows user's encrypted credential storage.

Each client uses its **own** broker account and local execution journal. Paper/live selection is explicit. Mobile operating systems can suspend background networking; do not assume an unattended phone will always receive and execute instructions.

### C. Host or follow orders across devices

1. Deploy or select a reachable **HTTPS relay** using [Remote Host / Receive setup](docs/remote-connect-setup.md). The repository does **not** provide an already-running public service. Keep the relay's SQLite disk persistent and operate a single service worker.
2. Connect each device to its **own Alpaca account**, starting with paper accounts.
3. Create a host channel and share a private, single-use invitation with each follower. Invitations expire after ten minutes; each receiver gets its own credential.
4. Verify the **role, environment, account, and pricing policy** on each device. Followers start paused; explicitly enable new entries only after paper testing.
5. Place an order **inside Crier** on the host. Followers receive the instruction without waiting for a host fill. Track each follower's broker order independently.

The relay transports instructions; it does **not** hold brokerage API credentials or execute orders. It **can see the instructions** and must be operated by someone you trust. Revoking relay access stops future transport, **not** existing broker orders.

For the browser/Python intent device, open `/intent`. Its optional Alpaca execution adapter requires `CRIER_INTENT_ENV`, `CRIER_INTENT_ALPACA_KEY`, `CRIER_INTENT_ALPACA_SECRET`, and `CRIER_INTENT_ALPACA_ACCOUNT` (the verified Alpaca account UUID). See [Intent mirroring](docs/intent-mirroring.md) for setup and behavior.

## Order semantics and recovery

- **Enter:** creates a durable instruction for a new tracked trade.
- **Replace:** requests cancellation/reconciliation of the previous entry remainder before attempting the revised target.
- **Cancel:** invalidates unfilled entry remainder; it does **not** sell holdings already acquired.
- **Exit:** attempts to sell holdings attributable to the tracked trade, bounded by broker-reported availability and the requested quantity.
- **Pause:** blocks new entries; it does not automatically close positions or guarantee cancellation of working orders.

Clients use durable journals and client order IDs to avoid blindly reposting an order after an uncertain submission. Broker network failures and cancellations can still leave outcomes **unresolved**; check the broker before taking further action. A stale instruction may expire instead of executing. The [intent protocol](docs/protocol/intent-v1.md) and [paper acceptance procedure](docs/intent-paper-acceptance.md) describe the contract and required validation.

**Completion work:** Cancellation recovery now persists retry timing and requires a fresh broker lookup, including after restart. Future-created entries wait for their validity window. The [completion roadmap and phase graph](docs/project-completion-roadmap.md) track remaining protocol/rejection coverage, client setup and Discord parity, hosting, signed releases, Webull access, and real-device acceptance. Automated regression tests do not establish unattended live-money readiness.

## Data and security

- Broker credentials remain on the executing device, not in relay events.
- Pairing credentials authorize channel publishing or reading; keep them private.
- Use HTTPS for remote access. The local development HTTP exception is for loopback only.
- Keep local journals, pairing files, and persistent relay storage; deleting them can destroy recovery context.
- Keep a single active monitor/publisher per account and Discord destination to avoid independent duplicate alerts.
- Never commit API keys, access tokens, invitation links, webhooks, or data directories.

Read [native data handling](docs/native-data-handling.md), [execution architecture](docs/live-execution-architecture.md), and [remote deployment](docs/remote-connect-setup.md) before deployment.

## Test and build

```sh
python -m pip install -e ".[test]"
python -m pytest -q
python -m compileall -q crier
node --check crier/static/app.js
```

Tests primarily use fixtures and mocked transports; they do **not** establish live broker correctness. Native compilation, signing, physical-device operation, cross-network delivery, and paper-account execution require separate verification. Consult the [iPhone release checklist](docs/iphone-release-checklist.md) and [cross-device paper acceptance procedure](docs/intent-paper-acceptance.md).

## Documentation

- [Completion roadmap and implementation phases](docs/project-completion-roadmap.md)
- [Intent mirroring and execution behavior](docs/intent-mirroring.md)
- [Remote connection deployment](docs/remote-connect-setup.md)
- [Windows desktop](desktop/README.md) · [iOS](ios/BUILD.md) · [Android](android/README.md)
- [Alpaca fill monitor](docs/alpaca-setup.md) · [Monitor and Discord publisher](docs/monitor-publisher.md)
- [Webull validation](docs/webull-validation.md) · [Tradier validation](docs/tradier-validation.md)
- [Source and reuse references](docs/source-references.md)

**License:** MIT.
