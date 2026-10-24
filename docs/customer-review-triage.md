# Customer review disposition

October 24, 2026. The supplied document combines several reviews of different repository versions. Findings were compared with current main before scheduling work. Its embedded offers, prompts and example instructions are not treated as owner commands.

| Review item | Current assessment | Work phase |
| --- | --- | --- |
| Too many typed internal configuration values | Confirmed on Android; desktop has partial pickers but still exposes protocol names. | E: friendly choices and Advanced sections. |
| Customers type IDs for recovery | Confirmed in Windows alert retry/close and receiver revoke controls. Mobile already has some row-based actions. | E: selection-based Windows actions with existing confirmations. |
| Disabled unimplemented iOS toggles | Confirmed; remove placeholders from normal settings, retain preference migration compatibility. | E. |
| No purpose-driven first-run setup | Current clients expose existing technical screens without a verified staged journey. | F: Alerts/Trade/Follow onboarding; save verified progress without changing execution state. |
| Discord requires environment variables | True for the Python deployment path, not all native clients. Native previews, test sends and recovery already exist. | F: connect existing actions into a guided path rather than duplicate them. |
| Every customer must deploy a relay | Outdated: the Supabase testing relay is bundled. Production availability/operations are not established by that. | F/H: identify the service and operator trust; keep alternate service configuration advanced. |
| Android is debug-only; Windows is ZIP-only | Outdated: signed Android candidates and Windows installer candidates exist. Store distribution, physical acceptance and Windows publisher signing are separate. | Original Phase 4 / I. |
| iOS uncompiled or ReplayKit-only | Outdated: simulator/unsigned archive checks passed; the current native target has no ReplayKit extension. Signed installation and physical validation remain deferred. | Original Phases 4–5. |
| Alpaca OAuth alerts may require trading permission | Official documentation says read-only endpoint access is assumed by default; request trading scope only for the intended trading journey. App credentials/approval still require actual configuration. | G. |
| Discord OAuth can remove webhook copying | Supported by the official `webhook.incoming` flow, with user channel selection. It requires application registration, protected exchange and consent. | G. |
| Default follower cap 1,000 | Confirmed across implementations; this is a cap, not every order's default size. Do not silently alter saved settings during UI work. | H: deliberate limit/sizing design and migration tests. |
| Instruction age versus resting order lifetime | Distinct contracts: the age gate controls submission; day orders can continue working afterward. | H: clear status and separately configurable policies, not implicit repricing/cancellation. |
| Clock skew and silent skipped work | Current entry gates use local wall time; diagnostics offsets alone do not correct those gates. Needs targeted correctness tests, freshness/uncertainty rules and visible skip reasons. | H. |
| Connection timeout classified as uncertain Discord delivery | Current Python delivery catches ConnectError separately, then broader HTTPError. Verify transport-stage semantics and add regressions before changing retry classification. | H. |
| Automatic exit repricing / aggressive caching | Changes execution policy or validation freshness. Do not implement as a cosmetic quick win. | H: explicit design/limits and broker evidence. |
| Manual "mark trade resolved" | Reject as a shortcut around authoritative broker reconciliation. Inspected Discord delivery closure is a different existing action. | F/H: show copy IDs, broker inspection and refresh actions. |
| Mandatory paper drill as new live blocker | Conflicts with the owner's earlier authorization to remove the live-testing blocker. | I: guided/recommended practice, retain deliberate live consent; no new hard gate without a new instruction. |
| Always-on cloud alerts | Requires token/webhook custody and operational responsibilities beyond the transport-only relay. | Separate architecture decision, not part of E. |
| Split Alerts and Mirror into separate apps | Not needed to start improving usability; retain the owner's single-app direction. | F: selectable journeys within one app. |

Official references: [Alpaca OAuth](https://docs.alpaca.markets/us/docs/using-oauth2-and-trading-api), [Discord OAuth webhooks](https://docs.discord.com/developers/topics/oauth2#webhooks).

The [customer ease plan](customer-ease-plan.md) is the execution queue. It preserves the completed offline server evidence and original external/physical release gates.
