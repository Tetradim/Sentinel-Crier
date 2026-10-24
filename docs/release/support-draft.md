# Sentinel Crier support page draft

**Support route approved; page draft not published or approved.** The owner has
approved public GitHub Issues for support. This page draft does not establish a
response-time commitment or a complete App Store Support URL. The distributor must add
its actual contact details and approve a private route for sensitive reports.

## Help with Sentinel Crier

Sentinel Crier's iPhone app currently connects to Alpaca paper/live accounts.
Webull connectivity is not available in this release. Keep the app active for
account monitoring, Discord fill alerts and host/receiver mirroring. The optional
PC monitor is installed and configured separately.

For an uncertain order, inspect the order and fill history directly with Alpaca
before retrying. Disconnecting or revoking a receiver does not cancel an order
already submitted. Preserve the local journals: they support reconciliation and
duplicate prevention. Do not erase app data as a first troubleshooting step.

For a missing Discord alert, check the selected environment and destination, the
app's delivery state and the actual Discord channel. An uncertain post may already
have succeeded; retrying can create a duplicate. First connection baselines older
fills instead of posting them. Removing the webhook stops future delivery but does
not remove messages already posted. Pending local fills can reach a newly configured
webhook. Use one publisher per account/destination when running a PC monitor too.

## Public issue route

Non-sensitive bugs and feature requests can be reported at
[Sentinel Crier issues](https://github.com/Tetradim/Sentinel-Crier/issues), the
owner-approved support route. The repository was public and Issues were
enabled when checked with `gh repo view` on 2026-10-24. No response time is promised.

Include platform, app version/build, approximate time and time zone, paper/live
label, steps, expected behavior and the exact visible error after redaction. Crop
screenshots to remove balances, account identifiers and other people's information.
Diagnostic exports can contain order IDs, event IDs, quantities, prices, timestamps
and broker responses; inspect and redact them before sharing.

Never post API keys/secrets, Discord webhook URLs, pairing tokens or invitation
links/codes, signing keys, account numbers or unredacted trading journals in public
issues. If a credential was exposed, revoke/rotate it with the relevant provider.
Use the owner's approved private contact for privacy/security or account-specific
reports once that contact exists.

## Owner completion before publication

- Supply the distributor's real identity and actual reachable contact details;
  approve a private privacy/security route and who handles requests.
- Select and operate a public support page URL; verify access without a GitHub
  login, on a phone, and from the intended distribution regions.
- Add the approved privacy-policy link and review the wording against the exact
  release build. Do not paste this draft's unresolved instructions into metadata.
- Apple's [Support URL field](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/)
  calls for actual contact information so users can reach the developer. A public
  issue tracker is the approved support route, not proof that this requirement is met.
