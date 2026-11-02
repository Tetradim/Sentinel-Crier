Crier 0.5.2 brings the Windows workspace closer to Crier's mobile interface.

The dark account-first layout includes persistent account and PAPER/LIVE/OFFLINE context, Home/Markets/Trade/Positions/Orders navigation, an Account hub for setup and recovery, and a visible Stop all control. Stock and option tickets use stacked inputs, separate order management, and scrollable tables. Status messages and recovery actions remain reachable at scaled window sizes.

Stop all also invalidates pending pairing callbacks and queued reconnects, including when the selected connection changes during shutdown. Existing execution authorization, frozen order commands, ownership journals and allocation checks remain in place. Unavailable balances and chart feeds are explicitly marked unavailable.

Before installing, stop Crier workers and create a private recovery snapshot. The updater checks compatibility, hashes and the signed update catalog; installation remains explicit. The Windows installer remains Authenticode-unsigned. Android 0.5.1 remains the separately published mobile package; this Windows update does not change its UI.

Apple enrollment/signing, physical-device/broker acceptance and Webull/provider activation remain owner-deferred. No real brokerage orders or customer notifications are part of automated acceptance.
