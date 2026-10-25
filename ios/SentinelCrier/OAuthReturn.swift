import Foundation

/// Preparation only. Login, installed deep-link handling and credential installation
/// require separate external configuration and integration. Never normalise/decode input.
enum OAuthReturn {
    private static let prefix = "sentinelcrier://oauth/complete?flow="
    static func validFlow(_ flow: String) -> Bool {
        flow.utf8.count == 43 && flow.utf8.allSatisfy {
            (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0) || $0 == 45 || $0 == 95
        }
    }
    static func parse(_ uri: String) -> String? {
        guard uri.utf8.count == prefix.utf8.count + 43, uri.hasPrefix(prefix) else { return nil }
        let flow = String(uri.dropFirst(prefix.count))
        return validFlow(flow) ? flow : nil
    }
    static func matchPending(_ pending: PendingOAuthReturn?, uri: String, expectedFlow: String,
                             expectedContext: OAuthReturnContext, now: TimeInterval) -> OAuthReturnContext? {
        pending?.matchReturn(uri, expectedFlow: expectedFlow, expectedContext: expectedContext, now: now)
    }
}

struct OAuthReturnContext: Equatable {
    let owner: String
    let provider: String
    let environment: String
    let purpose: String
    static func == (lhs: Self, rhs: Self) -> Bool {
        // Opaque authentication identities use byte equality, not Swift's
        // canonical Unicode string equivalence.
        lhs.owner.utf8.elementsEqual(rhs.owner.utf8) && lhs.provider == rhs.provider
            && lhs.environment == rhs.environment && lhs.purpose == rhs.purpose
    }
    init?(owner: String, provider: String, environment: String, purpose: String) {
        guard !owner.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, owner.count <= 256,
              ["alpaca", "discord"].contains(provider), ["paper", "live"].contains(environment),
              ["alerts", "trade"].contains(purpose), provider != "discord" || purpose == "alerts" else { return nil }
        self.owner = owner; self.provider = provider; self.environment = environment; self.purpose = purpose
    }
}

/// Memory only; integrators must clear pending on logout/session changes and supply
/// a trusted consistent clock. A match yields only the locally captured context for
/// future authenticated redemption. It never installs credentials or enables execution.
final class PendingOAuthReturn {
    private let flow: String
    private let context: OAuthReturnContext
    private let expiresAt: TimeInterval
    private let lock = NSLock()
    private var active = true
    init?(flow: String, context: OAuthReturnContext, expiresAt: TimeInterval) {
        guard OAuthReturn.validFlow(flow), expiresAt.isFinite else { return nil }
        self.flow = flow; self.context = context; self.expiresAt = expiresAt
    }
    func invalidate() { lock.lock(); defer { lock.unlock() }; active = false }
    func cancel() { invalidate() }
    func matchReturn(_ uri: String, expectedFlow: String, expectedContext: OAuthReturnContext,
                     now: TimeInterval) -> OAuthReturnContext? {
        lock.lock(); defer { lock.unlock() }
        guard active else { return nil }
        guard now.isFinite, now < expiresAt else { active = false; return nil }
        guard expectedFlow == flow, expectedContext == context, OAuthReturn.parse(uri) == flow else { return nil }
        active = false
        return context
    }
}
