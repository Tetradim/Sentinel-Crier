# Sentinel Crier for Windows

Native Windows app for the same submission-time mirroring channel used by Crier on
iPhone and Android. It supports Alpaca paper/live accounts. Webull Connect is not
implemented in this desktop release.

## Run

1. Download `SentinelCrier-Windows.zip` from the **Windows desktop** GitHub Actions
   artifact, or use the locally built ZIP in `dist/`.
2. Extract the entire ZIP to a normal folder. Keep `SentinelCrier.exe` and `_internal`
   together. Double-click `SentinelCrier.exe`. No separate Python install is required.
3. Open **Host / Receive**. Paste the invitation shared by the iPhone host.
4. Enter this PC account's Alpaca API key and secret. The account ID is discovered
   automatically. Paper credentials require a paper channel. Live channels require
   explicitly selecting **Allow connection to a live-money account**.
5. Click **Receive / reconnect**. Confirm the environment, account ID and follower role shown at
   the top. Connecting always starts new entries paused.
6. In **Pricing**, select exact-limit, bounded-limit or market pricing and save settings. In
   **Trading & activity**, click **Enable new entries** when ready to receive trades.
7. Place a trade **inside Crier on the iPhone**. Its order instruction travels through
   the relay immediately, without waiting for a host fill. PC activity shows the
   instruction and the PC account's own broker order status and filled quantity.

The phone and PC do not need the same brokerage account. Use separate paper accounts
for initial testing. No Discord parsing is involved in this connection.

## Pairing and network

For the new Host/Receive setup, see [one-time service deployment](https://github.com/Tetradim/Sentinel-Crier/blob/main/docs/remote-connect-setup.md).
Once that service is deployed, invite links supply its address automatically to receivers.
Use **Host / invite receiver** to originate trades from Windows and invite other devices.
After pairing, clear the invitation field and use the same button to reconnect with
saved credentials. Advanced pairing JSON and the original Connect button remain available.

Both apps still need a reachable HTTPS Crier relay. This executable is a desktop
trading client; it does not silently open router ports or provision public hosting.
Run the existing Crier service, expose it through your HTTPS setup, and create a
channel at `/intent`. Paste host JSON into iOS and follower JSON into Windows.
See [relay setup](https://github.com/Tetradim/Sentinel-Crier/blob/main/docs/intent-mirroring.md).
An iPhone cannot reach a PC's `localhost` address.

Keep Crier running and the PC awake. iOS must remain foregrounded for its current
network execution implementation. Minimize the Windows app to keep it running;
closing it stops receiving/executing. Existing broker orders remain at the broker.
Pause stops new entries while received cancel/exit instructions continue to be handled.
Disconnect stops all mirroring. These controls do not liquidate positions.

## Saved state and recovery

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
