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
| Financial-app distribution eligibility | **Unresolved: Apple guideline 3.2.1(viii), institution/permissions and available regions; enrollment alone is insufficient** |
| Signing certificate/profile | **Missing: Apple-issued matching identity/profile** |
| App Store Connect app record | **Missing: owner setup and app record** |
| Support contact | **Missing: owner-approved contact; blocks release** |
| Support route | Owner-approved public [GitHub Issues](https://github.com/Tetradim/Sentinel-Crier/issues); public/Issues enabled verified 2026-10-24 |
| App Store Support URL readiness | **Still incomplete: actual contact information required; validate the final support page against Apple requirements** |
| Privacy policy URL | **Missing: owner-approved public policy; blocks release** |
| In-app privacy access | **Missing: accessible policy link in current native UI; draft documents do not implement it** |
| Seller/legal identity | **Missing: owner input** |
| Category, age rating, availability | **Missing: owner decisions and Apple questionnaire** |
| App privacy answers | **Missing: owner review of native-data-handling.md and integrations** |
| Review contact/instructions | **Missing: owner input and safe review setup** |
| Export compliance | **Missing: owner determination in App Store Connect** |
| Screenshots | Existing repository images are references; accepted device sizes and current-build accuracy remain unverified |

Suggested description draft: “Sentinel Crier connects to your personal Alpaca
account to review positions and submit reviewed orders. Optional host/receiver
pairing shares order instructions at submission time, before broker confirmation;
an enabled follower can submit orders in its own Alpaca account under its local
settings. Optional Discord alerts report broker-confirmed fills with customizable
message templates and display formats. Paper and live environments remain
distinct. Keep the iPhone app active for monitoring and mirroring; an optional
separate PC service supports unattended monitoring.” Owner must approve this
against tested behavior before using it publicly. Do not imply Webull approval,
broker endorsement, continuous iPhone background monitoring, or investment returns.

Use [native data handling](native-data-handling.md) to prepare the privacy policy
and disclosures. A bundled privacy manifest does not replace either. Supply actual
URLs and contacts; do not publish placeholder addresses. A TestFlight upload
requires the owner's API key secrets and explicit workflow flag. No automated
Store submission is configured. Apple processing, beta review, tester access and
device acceptance remain separate manual gates.

## Prepared drafts and unresolved decisions

- [Privacy policy draft](release/privacy-policy-draft.md): source-based inventory,
  relay diagnostics, retention questions and App Privacy worksheet. It is not an
  approved policy and has no effective date or invented legal/contact details.
- [Support page draft](release/support-draft.md): public issue route is owner-approved
  and verified available; actual private contact information is missing.
  A GitHub issue tracker alone is not established as satisfying Apple's Support URL
  requirements. No hosting or publication has been performed.
- [App Review notes draft](release/ios-review-notes-draft.md): paper-only review
  setup and exact-build evidence still need preparation; no review credentials
  belong in the repository.

Apple's [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
3.2.1(viii) address financial trading/investing apps and the submitting institution,
licensing and permissions. The owner must establish an acceptable distribution
route with Apple and relevant permissions for each proposed region. This worksheet
does not determine legal status or predict approval. Guideline 5.1.1(i) requires a
privacy policy link both in metadata and accessibly within the app; the current
native UI has no such link. Runtime integration needs an approved public URL.
Apple's [platform version information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/)
describes the Support URL and confidential review-contact/demo-access fields.
Sources checked 2026-10-24; recheck against the intended submission date.

For each signed artifact retain its `release-manifest.json` with SHA-256, exact
commit, version/build, public endpoint and certificate/profile metadata. Never
attach `.p12`, `.p8`, decoded profiles, API credentials or private keys to a release.
