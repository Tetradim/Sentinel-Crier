# Sentinel Crier privacy policy draft and disclosure worksheet

**Draft for owner review, 2026-10-24; not an approved or published policy.** No
effective date, distributor identity, contact address, retention commitment or
deletion service has been invented. Complete the owner decisions below before
using this as a public policy. This covers the native iPhone build and optional
relay, not every possible configuration of the separate Python/PC installation.

## Source-based data handling

The app stores Alpaca API keys separately for paper/live environments and stores
the Discord webhook and pairing secrets in device-only Keychain entries. Settings
and pairing metadata use local UserDefaults. Protected local journals retain
account bindings, order instructions, broker order responses, actual fills,
outgoing delivery states and reconciliation identifiers. Intent journals also
retain diagnostics and archived resolved channels. Device-only Keychain attributes
do not establish a policy for journal backups or uninstall behavior.

Authenticated account, position, order, fill and quote requests go directly to
Alpaca. Orders use the selected paper/live endpoint. The broker receives the
authentication needed to service those requests. The relay does not receive
broker API keys. Network providers necessarily process connection metadata such
as IP addresses; the source alone does not establish their logging/retention settings.

Optional Discord sharing sends newly observed broker-confirmed fills, including
trades originating outside Crier, to the user's configured webhook. Templates can
include instrument, side, quantity, price and environment; time and a hashed
delivery reference are selectable, and the paper/live broker-confirmed provenance
is appended. User-written template text is also sent. Code-generated messages omit
raw account IDs, broker order IDs and credentials; a user can put sensitive text
in their own template. Channel viewers and Discord can access posted messages.
Testing the template sends a clearly labeled sample to that destination.

Optional submission-time host/receiver pairing sends instrument, enter/replace/
cancel/exit instruction, requested quantity/limit price, paper/live environment,
creation/expiry time, random event/trade IDs and revision numbers to the chosen
HTTPS connection service before broker confirmation. An enabled follower can
execute orders in its own account under local settings; host and follower fills
can differ. The deployed service may be the repository's Supabase Edge/Postgres
relay or another compatible operator. The operator must be identified in the final
policy; using Supabase does not by itself establish who operates this service.

The relay retains channel/environment data, invitation and pairing-token digests,
receiver identifiers, order events and diagnostic observations. Diagnostics include
sender/receiver observation times, clock offset/uncertainty, quote source/time,
bid/ask/last where available and quote-error status. They are shared with authorized
paired participants under the relay's scope rules to show delivery timing and
near-event quote comparisons. Local diagnostic timelines additionally contain
broker/client order IDs, dispatch details, responses and error text. A user can
export JSON/CSV with the system share sheet; recipients then receive that export.
This optional feature generates technical diagnostics even though no general
analytics or advertising SDK is included.

Legacy fill-based Mirror pairing, where configured, is distinct: it sends supported
execution events to a chosen HTTPS receiver using a hashed event identity, without
raw account/order IDs or brokerage keys. Its receiver can retain events and may
execute matching orders when Follow is enabled. Do not describe it as the same
trigger as submission-time intent pairing.

TradingView's hosted widget is disabled in the current source
(`commercialEmbedApproved = false`). It is not a source of current broker execution
data. If a future approved build enables it, its web content will make requests to
TradingView; a nonpersistent WebKit store does not prevent provider access to
network metadata. Verify provider practices and update the policy/disclosures
before enabling it. No advertising, tracking or third-party crash-reporting SDK
is configured in the current native project; Apple/system diagnostics and deployed
service logs must be reviewed separately before final claims are made.

## Controls, retention and deletion limits

Disconnecting stops active monitoring or relay work. Removing a webhook stops
subsequent sharing but does not erase already posted Discord messages or the
pending local fill queue. Changing the webhook can send pending fills there.
Revocation stops future receiver access; it cannot undo broker orders or copies
already received. Removing credentials does not erase the journals. Archiving a
resolved intent channel retains a local archive rather than deleting its history.
Deleting journals can remove duplicate-prevention and reconciliation evidence.

No fixed automatic deletion schedule for order/diagnostic relay records is
established by the repository migration. Invitation expiry is an access rule, not
a promise to delete every stored record. Operator backups, service logs, retention,
request verification and deletion procedures remain owner decisions. Alpaca,
Discord, receiver operators and export recipients retain their own records under
their policies. Do not promise that clearing app data deletes third-party records.

## App Store App Privacy worksheet — decisions still required

Apple's [App Privacy definitions](https://developer.apple.com/app-store/app-privacy-details/)
require evaluating retained off-device data and integrated partners, including
functionality-related collection. Optional features are not automatically exempt.
Treat this table as review prompts, not completed App Store Connect answers.

| Candidate data category | Evidence and owner review |
| --- | --- |
| Other Financial Info | Account/position/order/fill information and shared trade instructions; inspect actual retained data at each destination. |
| Identifiers / User ID | Channel, receiver, event/trade IDs, account bindings and credential digests; determine linkage across service records and paired participants. Hashing alone does not establish anonymity. |
| Other Diagnostic Data / Performance Data | Shared timing/clock/quote observations and retained logs; classify actual diagnostic fields and purposes. |
| User Content / Customer Support; Contact Info | User-authored Discord template and voluntarily supplied issues, exports or support correspondence; classify collection at the approved public issue route and any private contact once supplied. |
| Tracking, advertising, analytics and crash data | No corresponding native SDK configured; verify deployed relay/support providers, Apple diagnostics access and any future embedded content before final answers. |

App functionality is the evident purpose of execution and reconciliation paths;
the operator must confirm every use, retention period and identity linkage. Do not
select “Data Not Collected” solely because keys remain on the phone or the privacy
manifest declares no tracking. The manifest's UserDefaults reason is separate from
the App Privacy questionnaire and public policy.

## Owner completion and verification

- Identify the distributor and relay operator, real privacy contact, public policy
  URL, effective date, supported regions and policy-change process.
- Approve retention periods and an operational request/deletion process covering
  active records, archives, logs and backups, plus third-party limitations.
- Inventory the deployed endpoint and infrastructure configuration, downstream
  receiver access, diagnostic sharing and any broker/provider agreements.
- Approve each privacy answer against the exact signed build and service; add an
  accessible in-app policy link (currently absent). Obtain review appropriate to
  the intended regions without treating this worksheet as a legal determination.

Evidence: `ios/SentinelCrier/{AlpacaREST,AlpacaJournal,StandaloneConfiguration,
AlpacaAlertFormatter,IntentMirroring,IntentDiagnostics,QuickConnection,
TradingViewHostedChart}.swift`, `ios/project.yml`,
`supabase/migrations/202610230001_relay.sql`, and
[native data handling](../native-data-handling.md). Recheck when these change.
