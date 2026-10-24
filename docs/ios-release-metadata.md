# iOS release metadata worksheet

Status: **blocked for release**. Candidate version is read from root `release.json`
(currently 0.2.0). No Apple Developer account exists for this owner; no signed
package or Apple distribution eligibility has been verified. Physical testing is
deferred by owner. This worksheet is preparation, not an App Store submission.

| Field | Prepared value or required owner input |
| --- | --- |
| Display name | Sentinel Crier |
| Bundle ID | `com.tetradim.sentinelcrier` (owner must register/confirm availability) |
| App Group | `group.com.tetradim.sentinelcrier` |
| Version | Root `release.json` |
| Build number | Explicit dispatch value greater than highest previous upload |
| Developer account/team | **Missing: owner enrollment and Apple team** |
| Signing certificate/profile | **Missing: Apple-issued matching identity/profile** |
| App Store Connect app record | **Missing: owner setup and app record** |
| Support contact | **Missing: owner-approved contact; blocks release** |
| Support URL | **Missing: owner-operated public support page; blocks release** |
| Privacy policy URL | **Missing: owner-approved public policy; blocks release** |
| Seller/legal identity | **Missing: owner input** |
| Category, age rating, availability | **Missing: owner decisions and Apple questionnaire** |
| App privacy answers | **Missing: owner review of native-data-handling.md and integrations** |
| Review contact/instructions | **Missing: owner input and safe review setup** |
| Export compliance | **Missing: owner determination in App Store Connect** |
| Screenshots | Existing repository images are references; accepted device sizes and current-build accuracy remain unverified |

Suggested description draft: “Sentinel Crier connects to your personal Alpaca
account to review positions, submit explicitly confirmed orders, and publish
verified execution alerts to your configured Discord destination. Paper and live
environments remain distinct. Monitoring while the app is suspended is limited;
an optional PC service supports unattended operation.” Owner must approve this
against tested behavior before using it publicly. Do not imply Webull approval,
broker endorsement, continuous iPhone background monitoring, or investment returns.

Use [native data handling](native-data-handling.md) to prepare the privacy policy
and disclosures. A bundled privacy manifest does not replace either. Supply actual
URLs and contacts; do not publish placeholder addresses. A TestFlight upload
requires the owner's API key secrets and explicit workflow flag. No automated
Store submission is configured. Apple processing, beta review, tester access and
device acceptance remain separate manual gates.

For each signed artifact retain its `release-manifest.json` with SHA-256, exact
commit, version/build, public endpoint and certificate/profile metadata. Never
attach `.p12`, `.p8`, decoded profiles, API credentials or private keys to a release.
