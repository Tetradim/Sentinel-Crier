# Sentinel Crier

**Trade inside Crier, share orders between paired devices, and publish trade alerts to Discord.**

Crier is an open-source app for iPhone, Android and Windows. A host originates stock or option orders inside Crier; paired receivers follow through their own brokerage accounts. Discord publishing is a separate, optional workflow. Copying does not require another bot to parse Discord messages.

The current native trading integration is **Alpaca**, with paper and live environments. Webull Connect remains pending approval and integration. Automated checks have passed; signed iPhone distribution and real-device/broker acceptance remain unfinished.

## Choose a workflow

| Mode | What it does |
| --- | --- |
| Alerts only | Observe supported account fills and publish customizable Discord alerts without enabling copy trading. |
| Trade in Crier | Enter and manage supported Alpaca orders directly from the app. |
| Host | Share enter, replace, cancel and exit instructions with privately paired receivers. |
| Receive | Follow the host through your own Alpaca account with your selected sizing, pricing and exit settings. |

Native trading supports **whole-share stocks and standard long single-leg options**. The separate Python observer also handles eligible fractional stock fills. Independent signal entries, protective stops, trailing strategies and automatic limit-to-market fallback remain future proposals.

## How copying works

1. Configure each device's own brokerage account and environment.
2. The host creates a private invitation; the receiver accepts it. Invitations are single-use and expire after ten minutes.
3. The receiver reviews its execution settings and explicitly enables new entries. They start paused.
4. An order entered inside Crier publishes its instruction without waiting for the host's fill.
5. Each device reconciles its own broker orders and reports its own results to the Copy dashboard.

Any supported platform can take the Host or Receive role. Devices can use different networks. The apps include a [Supabase testing relay](crier/connection-service.json), so customers do not need a home server, open router ports or their own Supabase project. The current pairing flow uses scoped device tokens.

**Push delivery is implemented.** An authenticated stream delivers durable instructions; database notifications wake the hosted service after writes commit. Bounded polling is the labeled recovery path. Reconnect replays saved records while durable identities suppress duplicate submissions. See [push delivery and the dashboard](docs/push-dashboard.md).

The relay transports instructions and observations; it does not execute trades or hold broker API keys. Credentials remain on the executing device through Windows DPAPI, iOS Keychain or Android's encrypted Keystore-backed vault. The relay operator can see instruction contents. The separately prepared provider OAuth service has different credential custody and is not activated; see [provider connections](docs/provider-connections.md).

An instruction, a submitted order and a fill are different events. Networks, broker checks, liquidity and operating-system suspension affect execution. Crier does not guarantee delivery time or identical fill prices.

## Execution controls

| Control | Current behavior |
| --- | --- |
| Entry size | Source quantity, fixed units, ratio or per-trade budget. Host quantities are not scaled. |
| Price | Exact limit, bounded limit or explicitly selected market pricing. Initial market selection is different from automatic fallback. |
| Limits | Source quantity cap, separate local target cap, optional entry notional cap and submission-age limit. |
| Exit size | Requested units, proportional source-intent exits or close remaining tracked units. |
| Entry timeout | Optionally cancel acknowledged working entries after reconciliation; acquired holdings are not automatically sold. |
| Pause | Block new entries while preserving authorized cancellation/exit handling. It does not liquidate positions. |

Policies apply to new trades; settings changes do not silently rewrite open trades. Durable identities, account/environment checks, fresh broker evidence and tracked ownership constrain execution. Unknown submissions reconcile before another order is attempted. Cancel requests are not proof of cancellation; partial fills remain holdings. A host cancel invalidates an unfilled entry remainder, while a host exit requests sale of tracked holdings.

The current per-trade budget is **not** a recurring stock-card allocation or shared stock/options funding pool. See [execution settings](docs/execution-policies.md) and the [intent protocol](docs/protocol/intent-v1.md).

## Discord alerts and diagnostics

Alerts offer configurable fields and card/plain-text formats. iOS and the Python publisher also support Homebrew-style layouts. Instrument, side, quantity, fill price, timestamp and provenance appear when supported and available. Manual receipts remain user-confirmed evidence rather than broker-verified fills.

Choose **Alerts only** on iPhone, **Alerts** on Android, or **Start here → Send my fills to Discord** on Windows. Configure the destination, inspect a preview and explicitly enable publishing. These routes need no pairing and do not activate trading workers. Reconnect/restart requires fresh publishing permission. See [monitor/publisher operation](docs/monitor-publisher.md).

The read-only **Copy dashboard** shows instructions, device results, quantities, fill averages and remaining units. Actual host/receiver price comparisons, eligible P&L calculations, clock-adjusted delivery estimates and JSON/CSV exports require appropriate evidence. Missing prices or fees are not invented. See [execution diagnostics](docs/execution-diagnostics.md) and [dashboard calculation and privacy limits](docs/push-dashboard.md).

## Platforms and installation

| Platform | Implementation | Distribution and operating limits |
| --- | --- | --- |
| iPhone | Native Alpaca trading, alerts, Host/Receive, dashboard and health/recovery. Account operations do not require a PC or Python server. | Simulator and unsigned hardware archive verified. Apple enrollment/signing is required for installable distribution. Suspension can stop networking. |
| Android | Native Alpaca trading, alerts, Host/Receive, dashboard and health/recovery. | Signed candidate APK/AAB builds produced. Physical/background acceptance remains deferred. |
| Windows | Alpaca desktop app, alerts, Host/Receive, dashboard, health, optional tray and sign-in startup. | Installer/portable candidates produced; installer lifecycle tested. Publisher signing is absent. Keep the PC awake. Sign-in startup begins disconnected. |
| Python | Local monitor/publisher console, manual receipt review and separately configured intent execution. | Python 3.11+; optional local or hosted connection service. |

- [iPhone build](ios/BUILD.md) · [distribution checklist](docs/iphone-release-checklist.md)
- [Android setup](android/README.md) · [release packages](docs/android-release.md)
- [Windows setup](desktop/README.md) · [installer and updates](docs/windows-release.md)
- [Customer setup, paper practice and recovery](docs/customer-acceptance.md)

The current iPhone target has no ReplayKit extension and does not continuously observe other brokerage apps' screens. Submission-time mirroring applies to orders placed **inside Crier**. Supported fill monitoring can observe activity originating elsewhere later; it cannot infer that other app's original button press instantly. Mobile background execution remains constrained by the operating system.

## Broker availability

| Broker | Scope today |
| --- | --- |
| Alpaca | Implemented paper/live native trading and Python monitoring/execution paths. Real account/device acceptance is separately tracked. |
| Tradier | Read-only Python polling adapter requiring account-specific validation; no native Tradier copy executor. |
| Webull Trading API | Experimental Python SDK observer with separate access and verification requirements. |
| Webull Connect | Candidate server authorization/token-custody components with offline evidence. Approval, deployed authorized integration, native login and order adapter remain unfinished. |

Multiple hosts, simultaneous broker-account routing and copying across different brokers remain [deferred D.1](docs/deferred/multi-host-cross-broker.md). A donor bot's adapter name does not establish working support in Crier.

## Run the Python console

```powershell
git clone https://github.com/Tetradim/Sentinel-Crier.git
cd Sentinel-Crier
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m crier serve
```

On macOS/Linux, activate with `source .venv/bin/activate`. Open **http://127.0.0.1:8765** using the private token generated in `data/access-token`. The default launch selects no broker and leaves Discord delivery disabled.

For Alpaca paper fill monitoring, set process environment variables before starting:

```powershell
$env:ALPACA_ENV = "paper"
$env:APCA_API_KEY_ID = "YOUR_PAPER_KEY"
$env:APCA_API_SECRET_KEY = "YOUR_PAPER_SECRET"
python -m crier serve --monitor alpaca
```

The first complete poll establishes a baseline without publishing historical fills. Later fills are journaled and queued. The CLI does not automatically load `.env`; Docker Compose loads it separately. See [Alpaca setup](docs/alpaca-setup.md) and [.env examples](.env.example).

For Python publishing, set `DISCORD_WEBHOOK_URL`, `CRIER_PUBLISHER_VERIFIED=true` and `CRIER_DELIVERY_ENABLED=true` before restarting. Review the destination and queue first: enabling delivery can publish queued records. Inspect uncertain deliveries before explicitly retrying because Discord may already have received them. The fill observer is read-only; [optional intent execution](docs/intent-mirroring.md) has separate credentials and permissions.

## Verification and project status

Reporting-repair source `a7b332b` passed **1,033 Python tests**, with one optional SDK skip, **165 Android unit tests** and **160 iOS native tests**, plus UI/build and Windows installer checks. Seven successful CI runs and report hashes are recorded in [accepted evidence](docs/acceptance/2026-10-26/reporting-recovery/README.md). These counts describe that revision, not physical or real-broker acceptance.

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

Platform guides describe native builds. [Webull server operations](docs/webull-server-operations.md) and its [capability report](docs/acceptance/2026-10-24/webull-offline-acceptance.json) cover the separate offline candidate. For your own relay, see [remote connections](docs/remote-connect-setup.md) and [Supabase setup](docs/supabase-setup.md).

External dependencies include Apple signing/enrollment, Webull approval/integration, provider registration/activation, physical cross-network and broker-UI acceptance, real Discord delivery and production relay operation. Automated acceptance does not mark those complete.

- [Remaining work and phase status](docs/remaining-work.md)
- [Future scope: policies, funding and routing](docs/future-scope.md)
- [Sentinel source inventory](docs/sentinel-feature-inventory.md)
- [Native data handling](docs/native-data-handling.md)
- [Support and bug reports](https://github.com/Tetradim/Sentinel-Crier/issues)

**License:** [MIT](LICENSE).
