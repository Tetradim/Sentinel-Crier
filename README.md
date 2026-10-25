# Sentinel Crier

**Trade alerts and optional cross-device order mirroring for iPhone, Android and Windows.**

Crier can publish customizable Discord messages about trades and share order instructions directly between paired devices. Discord is optional for device-to-device mirroring: each receiver connects to the relay and executes through its own brokerage account.

The implemented trading clients currently use **Alpaca**. **Webull Connect is not available in released clients**; its server components have passed offline integration tests, while approval and actual broker integration remain pending.

## Three ways to use Crier

| Workflow | What happens |
| --- | --- |
| Monitor and publish | Observe supported brokerage execution records, preserve a local history and publish confirmed-fill alerts to Discord. |
| Trade inside Crier | Use the native client to enter and manage supported Alpaca orders. The iPhone app connects directly to Alpaca and does not require the Python application or a PC for its own account operations. |
| Host / Receive | Orders entered inside Crier publish enter/replace/cancel/exit instructions to paired receivers before waiting for the host's fill. Each receiver applies its own execution settings and tracks its own broker result. |

**An order instruction, a submitted order and a confirmed fill are different events.** Crier preserves those distinctions in alerts and diagnostics. Manual observations remain labeled as user-confirmed evidence.

## Current platform and broker scope

| Component | Current status |
| --- | --- |
| iPhone | Native Alpaca client, Discord alerts, Host / Receive and diagnostics. Simulator and unsigned hardware archive checks passed. Installable distribution still requires Apple enrollment/signing. |
| Android | Native Alpaca client, Discord configuration, Host / Receive, recovery and diagnostics. Signed candidate APK/AAB builds produced; physical acceptance remains deferred. |
| Windows | Alpaca desktop client, Host / Receive, Discord configuration and diagnostics. Installer/portable candidates produced; installer lifecycle tested in CI. Publisher signing is absent. |
| Python console | Local monitor/publisher, manual receipt review, alert preview/history and optional intent execution. |

**Provider OAuth:** The separate Supabase service and Windows/iOS/Android customer sign-in, return handling and credential installation are implemented. Activation still needs deployment, registered Alpaca/Discord applications and real consent acceptance. API-key/webhook setup remains available. See [provider connection status](docs/provider-connections.md).
| Alpaca | Paper/live clients for whole-share stocks and standard long single-leg options. The separate Python fill monitor also handles supported fractional stock fills. |
| Tradier | Read-only Python polling adapter; account-specific validation is required. |
| Webull Trading API | Experimental Python SDK observer with separate enrollment and verification requirements. |
| Webull Connect | Undeployed server libraries and candidate SQL: authorization, encrypted token custody, exchange/refresh coordination, revocation fencing, key rotation and cleanup. No working native Connect login or order adapter yet. |

Crier does not provide automatic background observation of arbitrary brokerage screens. The current iPhone target has no ReplayKit extension. Submission-time mirroring applies to orders entered **inside Crier**; observing a fill placed through another app does not reveal that app's original submission instantly.

## Start with a native client

Build and installation instructions:

- [iPhone](ios/BUILD.md) · [iPhone distribution checklist](docs/iphone-release-checklist.md)
- [Android](android/README.md) · [Android release packages](docs/android-release.md)
- [Windows](desktop/README.md) · [Windows installer and updates](docs/windows-release.md)

**Alerts without mirroring:** choose **Alerts only** in iPhone setup, **Alerts** on Android, or **Start here → Send my fills to Discord** on Windows. Verify Alpaca read access, configure the Discord destination and format, inspect a preview, optionally request a labeled synthetic test, then explicitly enable publishing. These routes need no Host/Receive pairing or relay and do not activate trading workers. Saved settings are reusable; reconnect/restart requires fresh publishing permission. See the platform guides above for baseline, polling, destination-history and foreground limits. Real account and Discord acceptance remains deferred.

For Host / Receive:

1. Open Connections and configure the device's own **Alpaca paper account**.
2. Choose **Host** on the originating device and create a private invitation.
3. Choose **Receive** on the other device and accept the invitation. Invitations expire after ten minutes and are single-use.
4. Check the role, account, environment and pricing/quantity limits. Receivers start with new entries paused; explicitly enable them when ready.
5. Place an order inside Crier on the host. Inspect each receiver's activity and broker result independently.

The clients bundle a **Supabase testing relay** through [the shared service configuration](crier/connection-service.json). Devices can communicate across different networks without opening customer router ports. The deployed relay uses durable bounded HTTP polling, not Supabase Realtime push, and offers no guaranteed trading latency or availability. Operators can configure a separate service using [remote connection setup](docs/remote-connect-setup.md) and [Supabase deployment](docs/supabase-setup.md).

The current relay transports instructions and diagnostic observations. It does not execute orders or hold broker API credentials. Its operator can see instruction contents. Broker credentials stay on the executing device; Windows uses DPAPI, iOS uses Keychain and Android uses its encrypted Keystore-backed vault.

Keep the receiving app running. iOS suspension can stop networking; Android background-service limits can interrupt work; Windows must remain awake. A persistent connection or overlay is not an all-day execution guarantee.

## Run the Python monitor and console

Requires **Python 3.11+**. From PowerShell:

```powershell
git clone https://github.com/Tetradim/Sentinel-Crier.git
cd Sentinel-Crier
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m crier serve
```

On macOS/Linux, activate with `source .venv/bin/activate`. Open **http://127.0.0.1:8765** and use the private token generated in `data/access-token`. The default launch selects no broker and keeps Discord delivery disabled.

To observe Alpaca paper fills, set process environment variables before starting:

```powershell
$env:ALPACA_ENV = "paper"
$env:APCA_API_KEY_ID = "YOUR_PAPER_KEY"
$env:APCA_API_SECRET_KEY = "YOUR_PAPER_SECRET"
python -m crier serve --monitor alpaca
```

The first complete poll establishes a baseline without publishing historical fills. Subsequent fills are journaled and queued. The CLI reads process environment variables; it does **not** automatically load `.env`. Docker Compose loads `.env` separately. See [Alpaca monitoring](docs/alpaca-setup.md) and [configuration examples](.env.example).

The normal fill observer is read-only. The Python application also includes a separately configured intent device that can submit/cancel orders. Its broker credentials and execution settings are independent of the monitor; see [intent setup](docs/intent-mirroring.md).

## Discord alerts

Clients provide preview, destination setup and platform-specific templates/fields. Formats include cards and plain text; iOS and the Python publisher also support Homebrew-style layouts. Alerts can show the instrument, side, quantity, execution price, timestamp and provenance when available.

For Python delivery, configure these variables and restart only after reviewing the destination and queued records:

```powershell
$env:DISCORD_WEBHOOK_URL = "YOUR_PRIVATE_DISCORD_WEBHOOK"
$env:CRIER_PUBLISHER_VERIFIED = "true"
$env:CRIER_DELIVERY_ENABLED = "true"
python -m crier serve --monitor alpaca
```

Enabling delivery can send previously queued records. Durable outboxes retain delivery evidence and uncertain outcomes; inspect an uncertain delivery before explicitly retrying, because Discord may already have received it. Manual receipts require review and remain identified as user-confirmed rather than broker-verified. See [monitor/publisher operation](docs/monitor-publisher.md).

## Mirroring and recovery

| Instruction | Meaning |
| --- | --- |
| Enter | Create a tracked trade instruction. |
| Replace | Reconcile/cancel the prior entry remainder before attempting the revised target. |
| Cancel | Invalidate the unfilled entry remainder; acquired holdings remain. |
| Exit | Attempt to sell holdings attributable to the tracked trade, bounded by available quantity. |
| Pause | Block new entries; existing orders and positions remain at the broker. |

Durable journals and client order IDs support restart reconciliation. Uncertain submissions are not blindly reposted. Cancellation requests are reconciled against fresh broker status; a request alone is not proof of cancellation. Revoking a receiver stops future transport and does not liquidate its account.

Start with separate paper accounts. Mirroring can place real orders when live execution is enabled, and account-specific fills/prices can differ. Preserve journals and pairing state when recovering an unresolved order.

[Execution diagnostics](docs/execution-diagnostics.md) include persistent timelines, sender/receiver events, reconciliation evidence, near-event Alpaca quote observations, premium comparisons, clock-adjusted delivery estimates and JSON/CSV export. Estimates are not guarantees of brokerage acknowledgement or fill latency.

## Development and verification

Python tests:

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

Candidate server tests require **Node 24** and **Deno 2.9.6**:

```powershell
npm ci --prefix supabase/tests
npm test --prefix supabase/tests
npm exec --yes --package deno@2.9.6 -- deno test supabase/webull-connect supabase/functions/crier/gateway_test.ts
node supabase/tests/offline-acceptance.mjs > webull-offline-acceptance.json
```

Latest server implementation evidence, source `6788b4c`:

- **542 Python tests** passed locally.
- **55 Deno tests**, **six SQL suites**, type checks and lint passed.
- **Nine integrated scenarios** exercised the coordinator, RPC adapter, actual SQL and encryption with synthetic authentication/transport.
- [PostgreSQL 17 CI](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40119328343) passed authorization, refresh, revocation, rotation and cleanup concurrency checks.

The [capability report](docs/acceptance/2026-10-24/webull-offline-acceptance.json) distinguishes implemented/synthetically integrated features from deployment and broker acceptance. Candidate Webull SQL remains **outside deployment migrations**. The tests do not place broker orders or send Discord messages. Native build evidence remains tied to its separately recorded source commits.

## Completion status and documentation

Phases A–D of the [autonomous implementation plan](docs/autonomous-completion-plan.md) are complete for their declared offline server scope. The [customer ease-of-use phases E–I](docs/customer-ease-plan.md) extend that work with clearer controls, guided onboarding and customer acceptance. The whole Webull product and physical release acceptance remain unfinished.

Remaining gates include an authenticated HTTP gateway and approved signed Webull transport, native Connect flows and order adapter, Webull approval/sandbox validation, Apple distribution requirements, finalized privacy/contact information and real-device/paper-account/Discord acceptance. These are tracked in the [full completion roadmap](docs/project-completion-roadmap.md).

- [Webull Connect status](docs/webull-connect.md) · [Candidate server composition and recovery](docs/webull-server-operations.md)
- [Cross-device paper acceptance](docs/intent-paper-acceptance.md) · [Phase 5 evidence](docs/phase5-results-2026-10-24.md)
- [Release status and deferrals](docs/phase4-status.md) · [Native data handling](docs/native-data-handling.md)
- [Intent protocol](docs/protocol/intent-v1.md) · [Source/reuse references](docs/source-references.md)
- [Support and bug reports](https://github.com/Tetradim/Sentinel-Crier/issues)

**License:** [MIT](LICENSE).
