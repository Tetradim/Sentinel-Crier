# Sentinel Crier for Windows

Native Windows app with read-only Alpaca fill alerts and optional submission-time
mirroring with iPhone and Android. It supports Alpaca paper/live accounts. Webull
Connect is not implemented in this desktop release.

## Alerts only — no mirroring setup

1. Open **Start here → Send my fills to Discord** (or the **Alerts setup** tab).
2. Choose paper or live and enter your own Alpaca key and secret. Live read access requires explicit permission. Choose **Connect / use saved keys**; the app discovers and verifies the account. Future connections can leave both key fields blank to reuse the same saved alerts account/environment.
3. After account verification, choose **Set up Discord: preview, test, enable**. Save your destination and format, then use the guided **Preview saved format** and optional **Send labeled test** actions. Inspect the test result; an uncertain acknowledgement requires checking Discord before retrying. Choose **Enable real alerts** when ready; pending alerts may then send. A successful test is not a mandatory gate.
4. Keep the PC awake and Crier running. The first complete fill fetch establishes a suppressed baseline; place a new paper trade after monitoring reports observing. Transient activity failures retain the cursor and show reconnecting rather than inventing fills.

This mode makes read-only Alpaca requests and creates no Host/Receive pairing, relay connection or order engine. Alerts credentials and each account/environment's Discord configuration, cursor and outbox are kept separately from the mirroring profile. Account/environment changes are rejected rather than silently reusing another journal. Disconnect before changing purpose; no connection or execution starts automatically on launch. Reconnect verifies the account again and requires fresh permission to publish; a saved enabled preference does not authorize this session. Format changes also pause publishing until explicitly re-enabled. Preview and test evidence clears when its account or saved configuration changes.

A fresh alerts profile can bind never-attempted pending messages to its first explicitly saved destination. Prior delivery attempts, uncertain results or a lost previously configured destination still require inspection/restoration; no messages are silently discarded or rerouted.

## Download and launch

1. Download `SentinelCrier-Windows.zip` from the **Windows desktop** GitHub Actions
   artifact, or use the locally built ZIP in `dist/`.
2. Extract the entire ZIP to a normal folder. Keep `SentinelCrier.exe` and `_internal`
   together. Double-click `SentinelCrier.exe`. No separate Python install is required.

For Discord alerts only, follow the alerts setup above. For trade mirroring, continue below.

## Tray and Windows sign-in options

In **Start here → Windows background options**, enable **Keep Crier running in the tray** if closing its window should leave monitoring running. Both background options are off by default. The tray offers **Show Crier**, **Pause new entries**, and **Quit Crier**. Quit stops workers through the normal disconnect flow; existing broker orders remain. A failed or stopped tray restores the window. The PC still needs to stay awake.

**Open Crier at Windows sign-in** is available in the packaged Windows app. It registers only the current user's installed executable, with no credentials in the startup command. It always opens disconnected and does not authorize orders or publishing. Reconnect explicitly, then enable the permissions you want. If tray mode is also enabled and its icon starts successfully, the sign-in launch begins in the tray. Disabling tray mode restores the window. Uninstall removes Crier's matching startup registration and preserves journals and credentials as before.

Source users can install the optional tray dependencies with `python -m pip install -e ".[desktop]"`; automatic sign-in registration requires the packaged executable.

## Follow another device's trades

1. Open **Host / Receive**. Paste the invitation shared by the iPhone host.
2. Enter this PC account's Alpaca API key and secret. The account ID is discovered
   automatically. Paper credentials require a paper channel. Live channels require
   explicitly selecting **Allow connection to a live-money account**.
3. Click **Receive / reconnect**. Confirm the environment, account ID and follower role shown at
   the top. Connecting always starts new entries paused.
4. In **Pricing**, select exact-limit, bounded-limit or market pricing and save settings. In
   **Trading & activity**, click **Enable new entries** when ready to receive trades.
5. Place a trade **inside Crier on the iPhone**. Its order instruction travels through
   the relay immediately, without waiting for a host fill. PC activity shows the
   instruction and the PC account's own broker order status and filled quantity.

The phone and PC do not need the same brokerage account. Use separate paper accounts
for initial testing. No Discord parsing is involved in this connection.

## Pairing and network

The app bundles the Supabase testing relay. Invite links supply its address automatically to receivers; customers do not need to deploy a service or open router ports. To operate your own service, see [remote connection setup](https://github.com/Tetradim/Sentinel-Crier/blob/main/docs/remote-connect-setup.md).
Use **Host / invite receiver** to originate trades from Windows and invite other devices.
After pairing, clear the invitation field and use the same button to reconnect with
saved credentials. Advanced pairing JSON and the original Connect button remain available.

Both apps need a reachable HTTPS Crier relay. The bundled service is for testing,
with no guaranteed availability or trading latency. Advanced pairing JSON remains
available for custom deployments; ordinary Host/Receive setup uses invitations.
An iPhone cannot reach a PC's `localhost` address.

Keep Crier running and the PC awake. iOS must remain foregrounded for its current
network execution implementation. Minimize the Windows app to keep it running;
closing it stops receiving/executing. Existing broker orders remain at the broker.
Pause stops new entries while received cancel/exit instructions continue to be handled.
Disconnect stops all mirroring. These controls do not liquidate positions.

## Saved state and recovery

In **Discord & receivers**, refresh delivery history or paired receivers, then select the actual row to inspect it. Retry, Close and Revoke act on that selection; no ID typing is needed. Refreshing or changing a connection clears stale selections. Failed messages can be explicitly retried after confirmation. Uncertain messages require inspection and may be closed without sending; their evidence is retained. Revoking a receiver stops future transport and does not cancel its existing broker orders. The delivery panel scrolls at smaller window sizes so record details and test/preview controls remain accessible.

Windows stores configuration and journals under `%LOCALAPPDATA%\SentinelCrier\Desktop`.
Pairing tokens and API credentials are encrypted with Windows DPAPI for the current
Windows user. Secrets are not included in the portable app folder or sent through
the relay. Leave connection fields blank to reuse saved settings. Restarting does
not automatically connect or enable entries.

The saved journal is pinned to its original account and pairing. Updating credentials
for that same account is supported while disconnected. Switching accounts/channels
in place is rejected to prevent abandoning unresolved orders. Do not delete a journal
to fix an unknown order; inspect its actual broker status first. Only one desktop
instance may use the data folder at a time.

With a **host** pairing the same app can originate buys and publish replace/cancel/exit
instructions. Select a tracked trade before changing it. Replace and Exit use the
quantity/price fields; Cancel uses the existing trade identity. Followers cannot
originate mirrored commands. Standard single-leg long options and whole shares only.

## Inspect execution evidence

Select a tracked trade in **Trading & activity**, open **Diagnostics**, and click
**Load selected trade**. Export JSON or CSV to keep the local relay and broker
timeline. Missing market quotes and unmeasured cross-device latency are labeled
explicitly. See [execution diagnostics](../docs/execution-diagnostics.md).

## Build from source

On Windows with Python 3.11+ (including Tcl/Tk):

```powershell
python -m pip install -e ".[test,desktop-build]"
python -m pytest -q
powershell -ExecutionPolicy Bypass -File desktop/build.ps1
```

Or run from source with `python -m crier.desktop` / `crier-desktop`.
The build runs an offline packaged smoke test that opens the UI invisibly and checks
local credential storage; it makes no broker or relay requests. The portable build is
unsigned and is not a Microsoft Store installer. CI includes the source tests and
the packaged smoke test. Physical cross-device testing remains separate:
[paper acceptance](https://github.com/Tetradim/Sentinel-Crier/blob/main/docs/intent-paper-acceptance.md).

## Installer and updates

Use the versioned per-user installer from the manual **Windows release** workflow for
normal installations. It preserves journals and DPAPI credentials across updates and
uninstall. Close the app before replacing program files; downgrade is unsupported.
See [Windows release and update instructions](../docs/windows-release.md) for release
checksums, signing status, build steps, and retained data details.

Provider sign-in is enabled only after the separate configured service returns valid
capabilities. The bundled Supabase project supplies the default `/functions/v1/crier-oauth`
base; operators can set `CRIER_OAUTH_SERVICE_URL` to another exact HTTPS Supabase
function base (20 lowercase project letters). No service/provider secrets are bundled.
Use Start here to choose alerts or trading, then Provider sign-in to create/sign in to
your Crier account and authorize a provider in your browser. Browser login must use
the same Crier customer. The per-user installer registers `sentinelcrier:` and forwards
opaque return notifications to the running app. A manual return URL field supports
uninstalled builds. Restarted apps reject old returns because device proofs remain
in memory. Cancel and start a new flow after an uncertain redemption.

A successful grant is verified and saved with Windows DPAPI only while disconnected;
reconnect explicitly with the saved credentials. Live access remains an explicit
reconnect checkbox. OAuth never enables broker orders or Discord delivery. Existing
pairing, account, journal and Discord outbox restrictions apply. A Discord grant
requires a previously verified saved account for the selected journey/environment.
Sign out disconnects workers and removes the customer session while retaining broker
recovery journals and saved broker credentials. Closing the app retains the encrypted
customer session; passwords and pending device proofs are never persisted. Session
refresh is explicit in the client API and never automatically retried after rotation.

OAuth credentials are also pinned to the exact provider-service URL and Crier customer
UUID. Reconnect and Discord enablement require that original customer/project sign-in;
a matching UUID in a different Supabase project does not satisfy the pin. Saved
customer sessions use the same service binding. Provider Bearer credentials without
ownership metadata are rejected; explicitly entered manual API keys retain the normal
account/environment recovery path. OAuth Discord ownership metadata is encrypted in
the same atomic destination write as the webhook, and survives reusing that webhook.

## Component health

Open **Health → Connections** for independent broker, fill-monitor, trade-sharing,
trade-receiving, execution-worker and Discord status. Checks observe the operations
Crier already performs; opening the panel sends no additional requests. Last successes
are saved per account/environment/connection, but restart and reconnect require fresh
checks. Stopped, waiting, idle, stale, blocked and degraded states have distinct meanings.
Idle sharing means there is no queued work, not proof that the relay is reachable.

Freshness is measured with a monotonic clock. A changed PC clock is displayed and
requires a clock check/reconnect; it does not silently extend execution instructions.
The panel offers setup, order activity, Discord history and disconnect actions.
**Health → Trade timeline** retains the existing execution evidence and exports.
Inspect unknown broker outcomes or uncertain Discord messages before retrying. Health
never resolves an order or grants trading/publishing permission. If health storage is
unavailable, the panel reports that separately; existing trading journals are retained.

Native mobile health and H.3 dispatch safeguards are also implemented. Optional Windows
tray/startup controls are described above. Optional follower sizing, exit and timeout controls are described in the [execution settings guide](../docs/execution-policies.md); they apply to new trades and save with entries paused.
