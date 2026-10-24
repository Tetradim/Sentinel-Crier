# iOS App Review notes draft

**Owner preparation only; not submitted.** Candidate version is from
`release.json`. No Apple Developer account, signed artifact, App Store eligibility,
review credentials or physical-device acceptance has been established. Physical
tests remain deferred by the owner. Do not paste incomplete instructions into
App Store Connect or put credentials in this repository.

## Resolve eligibility before preparing a submission

Apple's [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
3.2.1(viii) address financial-trading apps, the submitting financial institution
and required permissions in available regions. The owner must establish whether
Apple will accept the intended distributor and service model, and provide any
required evidence. Personal Alpaca API keys and a disclaimer do not establish
distribution eligibility. This draft makes no legal determination or approval claim.

## Confidential setup the owner must supply

Record the exact commit, version, build, signed IPA hash and device evidence.
Provide the real review contact's name, email and international-format phone in
App Store Connect. Prepare a permitted, working Alpaca **paper-only** test setup
and privately supply the necessary review access/instructions through Apple's
review fields. Verify paper options permissions and market-hours limitations if
the review scenario uses options. Do not require reviewers to use personal/live
brokerage credentials or expose an owner's production keys.

If mirroring is included in review, provide the actual HTTPS service base, a
permitted paper host/follower setup, available test receiver device/session and
an invitation flow that remains usable during review. Invitations are single use
and expire after ten minutes; a pasted expired code is not a review setup. Decide
how reviewers obtain fresh invitations and help from the supplied contact.
Provide a private test Discord destination/webhook if alerts are to be exercised.
Ensure no downstream bot can interpret paper tests as live trading signals.

## Candidate review explanation — approve against the tested build

Sentinel Crier connects directly to Alpaca using paper or live API credentials
stored in device-only Keychain. There is no Crier username/password login in the
native UI. Paper and live credentials/environments are separate. Use only the
supplied paper setup for this review.

From Home, open account settings/connections and save the paper credentials, then
connect and inspect account identity and positions. In Trade, review the exact
instrument, side, quantity, order type and limit before confirming an order. A
broker acceptance is not a fill. Test instructions must specify an actually
available instrument and explain market-hours/permissions limits for that build.

Optional Host/Receive pairing shares order intent when the host submits or changes
an order, before Alpaca confirmation. An enabled follower can place orders in its
own paper account according to its settings, including quantity, age and price
limits. Submission mirroring does not wait for the host's fill; follower fills
may differ. Revoke receiver access from the host connection UI to stop future
delivery; inspect broker orders separately for anything already submitted.

Optional Discord webhook configuration publishes newly observed broker-confirmed
fills, including fills made outside Crier. In Alerts, choose message format and
template, inspect the preview and use the labeled test message. Environment and
broker-confirmed provenance remain appended. The first successful connection
baselines prior fills instead of replaying them. Uncertain delivery requires
checking Discord before an explicit retry.

Keep Crier active for monitoring and mirroring. iPhone suspension/termination does
not provide continuous execution; the optional separately installed PC monitor is
not bundled iPhone background capability. No Webull connectivity, TradingView
hosted chart access, Discord-triggered automatic trading, automatic stop/take-profit
feature or investment-return claim should be inferred from this release's UI.
The current hosted chart is disabled pending permissions.

## Final submission gates

- Owner-approved public privacy/support pages, actual contacts and accessible
  in-app policy link; completed privacy answers against the deployed relay.
- Apple account/team, accepted app record and bundle/capability registration,
  valid matching signing identity/profile and a fresh upload build number.
- Approved regions/category/age-rating/export answers and current-build screenshots
  in accepted dimensions. Do not reuse reference images as evidence of this build.
- Safe review access rehearsed on the exact build, completed physical acceptance
  when authorized, and any financial-app eligibility evidence requested by Apple.

The manual signed workflow can optionally upload to TestFlight only when explicitly
selected and configured. It does not submit to App Review or grant tester access.
Apple processing and any beta review are separate gates. See the
[installation checklist](../iphone-release-checklist.md) and
[metadata worksheet](../ios-release-metadata.md).

Official fields and review-access requirements checked 2026-10-24:
[platform version information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/)
and [TestFlight overview](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/).
