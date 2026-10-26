# Customer setup and acceptance

## Install the appropriate artifact

| Platform | Current testing route | What remains separate |
| --- | --- | --- |
| Windows | Use the installer or complete portable ZIP from the [Windows release workflow](https://github.com/Tetradim/Sentinel-Crier/actions/workflows/windows-release.yml). Keep the portable executable and its bundled files together. | Check the release manifest for signing. Installer CI does not establish publisher trust or physical customer acceptance. |
| Android | Use an available signed candidate from [Android release packaging](https://github.com/Tetradim/Sentinel-Crier/actions/workflows/android-release.yml), or the debug APK from [Android build and tests](https://github.com/Tetradim/Sentinel-Crier/actions/workflows/android-build.yml) for development testing. | A debug APK is not store approval. Physical lifecycle, notification and background-service behavior need device validation. |
| iPhone | The current [iOS build workflow](https://github.com/Tetradim/Sentinel-Crier/actions/workflows/ios-build.yml) verifies a simulator build and unsigned hardware archive. | That archive is not an installable IPA or TestFlight release. Apple enrollment/signing and signed iPhone installation remain deferred. Simulator success does not close that gap. |

GitHub may require sign-in to download Actions artifacts. No separate Python installation is needed for the packaged Windows app. Avoid copying a lone executable out of its portable directory.

## Optional practice in the app

- **Windows:** Start here → Optional paper practice / support, or press F1. Escape closes the guide. Tab and Shift-Tab leave the read-only text area; scrolling and text copying remain available.
- **Android:** Optional paper practice / support on setup. Choose Alerts, Trade/share or Follow, then Return to setup.
- **iPhone:** Home → Optional paper practice. Choose a purpose and use normal Back navigation to return.

The guide is optional and read-only. It never connects an account, creates an invitation, sends a test, enables publishing, changes purpose or authorizes an order. No practice-completion flag gates live use. Existing account verification and deliberate live consent remain required for the actions that already need them.

For Alerts, verify the paper account, save the intended Discord destination, preview, optionally request a labeled synthetic test, and enable publishing explicitly. Wait for observing status before making a new supported paper fill. The first activity fetch establishes a suppressed baseline; an old fill is not evidence of first success.

For a mobile Alerts trial, using the brokerage on another device lets Crier remain in the foreground. Switching apps pauses foreground monitoring. After returning, check readiness: Android Alerts requires reconnecting after its foreground session stops; iPhone Crier reconciles a connected account and requires explicit publishing permission again. Confirm that state before expecting a pending fill to be posted.

For Trade/share and Follow, use the bundled testing relay through Host/Receive invitations. Customers do not need a home server or router port. Verify each account/environment and role, review the [current execution settings](execution-policies.md), then enable entries deliberately. Submission-time mirroring applies to orders entered inside Crier. Inspect actual broker records on both devices; a relay acknowledgement is not a fill. The bundled relay has no guaranteed trading latency or availability.

## Recovery without losing evidence

Open connection health, tracked-order history and Discord delivery history. Reconnect the original account and pairing for reconciliation. An unknown broker outcome must not be blindly replayed, cleared or manually marked resolved. Uncertain Discord acknowledgement needs inspection in the selected channel before any recovery action. Closing an inspected Discord delivery retains its evidence and does not send it again.

Cancellation stops the remaining buy when the broker confirms it; racing fills remain holdings. Use an explicit exit to close tracked holdings. Keep iPhone Crier in the foreground, Android workers available and Windows awake. Saved credentials or a saved enabled preference do not establish a current connection or fresh publishing/trading permission.

## First-success measurement remains a real trial

No real customer first-success time has been measured by automated acceptance. In a later authorized paper trial:

1. Record app/source version, platform, network type and selected purpose without credentials or account identifiers.
2. Start one observer's timer before setup. Record elapsed time at verified account, saved destination/pairing, optional test acknowledgement, explicit enablement and first actual new fill/order receipt.
3. Compare actual broker contract, side, quantity, limit, cumulative filled quantity and status. For Alerts, confirm the corresponding Discord message and delivery record.
4. Record interruption/recovery and any retries separately. Keep synthetic tests distinct from actual paper fills.
5. Report each timing's definition and scope. Clocks on different devices are not automatically synchronized; do not label an uncorrected timestamp difference as measured network latency.

The offline runner reports actual automated test-case durations with intercepted HTTP and synthetic data. Those are neither human setup times nor cross-device latency measurements. Real trials remain unpassed until performed.

## Accessibility and support

Android editable fields now expose native label associations and hints. Automated emulator checks cover those associations and guide navigation at enlarged font scale; iOS simulator checks cover guide navigation and screenshots. Windows tests cover guide navigation and read-only text traversal bindings. Actual TalkBack, VoiceOver, Narrator, largest text sizes, physical keyboards and device lifecycle checks remain deferred; no accessibility-compliance certification is claimed.

Use [Sentinel-Crier GitHub Issues](https://github.com/Tetradim/Sentinel-Crier/issues) for support. Include platform, app/source version, purpose, expected versus observed behavior and redacted error text. Remove passwords, API keys, bearer tokens, invitations, webhook URLs and account data. Do not post raw journals, credential files or unredacted logs. Opening support does not create an issue or upload data automatically.

## Reproduce the automated journey checks

```powershell
python -m pip install -e ".[test,oauth]"
python scripts/customer_acceptance.py --output build/customer-acceptance
```

Run from a checkout. The JSON/JUnit report records source revision, whether it was clean, passes/failures/skips and offline durations. A missing required journey cannot report success. Headless Linux may skip desktop UI tests; Windows UI initialization errors fail rather than becoming accepted skips. Native UI evidence comes from the [Customer acceptance workflow](https://github.com/Tetradim/Sentinel-Crier/actions/workflows/customer-acceptance.yml).
