import Foundation

// One atomic, protected journal owns submission identities and fill delivery state.
// Unknown submissions survive termination and are reconciled, never resubmitted.
actor AlpacaJournal {
    struct Submission: Codable, Identifiable {
        var id: String { ticket.id }
        let ticket: AlpacaTicket
        var order: AlpacaOrder?
        var state: String
    }
    struct Delivery: Codable, Identifiable {
        let id: String
        let environment: AlpacaEnvironment
        let accountID: String
        let fill: AlpacaFill
        var state: String
        var messageID: String?
        var retryAfter: Date?
    }
    struct State: Codable {
        var submissions: [Submission] = []
        var deliveries: [Delivery] = []
        var baselines: [String: String] = [:]
        var discordRetryAfter: Date?
    }
    private let file: URL
    private var state: State
    init(file: URL) throws {
        self.file = file
        if FileManager.default.fileExists(atPath: file.path) {
            state = try JSONDecoder().decode(State.self, from: Data(contentsOf: file))
        } else { state = State() }
    }
    static func local() throws -> AlpacaJournal {
        let folder = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        return try AlpacaJournal(file: folder.appendingPathComponent("alpaca-journal.json"))
    }
    private func save(_ next: State) throws {
        try JSONEncoder().encode(next).write(to: file, options: [.atomic, .completeFileProtectionUnlessOpen])
        state = next
    }
    func snapshot() -> State { state }
    func baseline(environment: AlpacaEnvironment, accountID: String) -> String? { state.baselines[environment.rawValue + ":" + accountID] }
    func setBaseline(_ value: String, environment: AlpacaEnvironment, accountID: String) throws {
        var next = state; next.baselines[environment.rawValue + ":" + accountID] = value; try save(next)
    }
    func begin(_ ticket: AlpacaTicket) throws {
        try ticket.validate()
        guard !state.submissions.contains(where: { $0.id == ticket.id }) else { throw AlpacaError.invalid("This review has already been submitted. Reconcile its client ID.") }
        guard !state.submissions.contains(where: { $0.ticket.environment == ticket.environment && $0.ticket.accountID == ticket.accountID && $0.state == "unknown" }) else { throw AlpacaError.invalid("Reconcile the unresolved order before another submission.") }
        var next = state
        next.submissions.append(Submission(ticket: ticket, order: nil, state: "unknown"))
        try save(next)
    }
    func reject(_ ticket: AlpacaTicket, status: Int) throws {
        guard [400, 401, 403, 422, 429].contains(status) else { return }
        var next = state
        guard let index = next.submissions.firstIndex(where: { $0.ticket == ticket && $0.state == "unknown" && $0.order == nil }) else { return }
        next.submissions[index].state = "rejected HTTP " + String(status)
        try save(next)
    }
    func record(_ order: AlpacaOrder, ticket: AlpacaTicket) throws {
        guard order.client_order_id == ticket.id, order.symbol == ticket.symbol,
              order.side == ticket.side, order.qty.flatMap({ Decimal(string: $0) }) == Decimal(ticket.quantity),
              order.limit_price.flatMap({ Decimal(string: $0) }) == ticket.limitPrice else { throw AlpacaError.invalid("Broker order does not match the saved ticket.") }
        var next = state
        guard let index = next.submissions.firstIndex(where: { $0.id == ticket.id && $0.ticket == ticket }) else { throw AlpacaError.invalid("Missing saved ticket.") }
        next.submissions[index].order = order; next.submissions[index].state = order.status
        try save(next)
    }
    func ingest(_ fill: AlpacaFill, environment: AlpacaEnvironment, accountID: String) throws {
        guard fill.activity_type == "FILL", !fill.id.isEmpty, !fill.order_id.isEmpty,
              let quantity = Decimal(string: fill.qty), quantity > 0,
              let price = Decimal(string: fill.price), price > 0 else { throw AlpacaError.invalid("Invalid broker fill evidence.") }
        let key = environment.rawValue + ":" + accountID + ":" + fill.id
        if let existing = state.deliveries.first(where: { $0.id == key }) {
            guard existing.fill == fill else { throw AlpacaError.invalid("Conflicting broker evidence for an existing fill ID.") }
            return
        }
        var next = state
        next.deliveries.append(Delivery(id: key, environment: environment, accountID: accountID, fill: fill, state: "pending", messageID: nil, retryAfter: nil))
        try save(next)
    }
    func claim(environment: AlpacaEnvironment, accountID: String, now: Date = Date()) throws -> Delivery? {
        guard (state.discordRetryAfter ?? .distantPast) <= now else { return nil }
        var next = state
        guard let index = next.deliveries.firstIndex(where: { $0.environment == environment && $0.accountID == accountID && $0.state == "pending" && ($0.retryAfter ?? .distantPast) <= now }) else { return nil }
        next.deliveries[index].state = "uncertain"
        try save(next)
        return next.deliveries[index]
    }
    func delivered(_ id: String, messageID: String) throws {
        guard !messageID.isEmpty, messageID.allSatisfy({ $0.isNumber }) else { throw AlpacaError.invalid("Discord did not return a message ID.") }
        var next = state
        guard let index = next.deliveries.firstIndex(where: { $0.id == id && $0.state == "uncertain" }) else { return }
        next.deliveries[index].state = "sent"; next.deliveries[index].messageID = messageID
        try save(next)
    }
    func retry(_ id: String, acknowledgeDuplicateRisk: Bool) throws {
        var next = state
        guard let index = next.deliveries.firstIndex(where: { $0.id == id }), next.deliveries[index].state != "sent" else { return }
        guard next.deliveries[index].state != "uncertain" || acknowledgeDuplicateRisk else { throw AlpacaError.invalid("Verify Discord first; retrying an uncertain delivery can duplicate it.") }
        next.deliveries[index].state = "pending"
        // Keep the server rate-limit deadline even for an explicit retry.
        try save(next)
    }
    func closeDelivery(_ id: String) throws {
        var next = state
        guard let index = next.deliveries.firstIndex(where: { $0.id == id && $0.state != "sent" }) else { return }
        next.deliveries[index].state = "closed by user"
        try save(next)
    }
    func hasOutstandingDeliveries() -> Bool {
        state.deliveries.contains { $0.state == "pending" || $0.state == "uncertain" || $0.state.hasPrefix("rejected") }
    }
    func refused(_ id: String, status: Int) throws {
        guard [400, 401, 403, 404].contains(status) else { return }
        var next = state
        guard let index = next.deliveries.firstIndex(where: { $0.id == id && $0.state == "uncertain" }) else { return }
        next.deliveries[index].state = "rejected HTTP \(status)"
        try save(next)
    }
    func rateLimited(_ id: String, retryAfter: Double) throws {
        guard retryAfter.isFinite, retryAfter >= 0 else { return }
        var next = state
        guard let index = next.deliveries.firstIndex(where: { $0.id == id && $0.state == "uncertain" }) else { return }
        next.deliveries[index].state = "pending"; next.discordRetryAfter = Date().addingTimeInterval(max(1, retryAfter))
        next.deliveries[index].retryAfter = next.discordRetryAfter
        try save(next)
    }
}

/// Shared synchronous fence survives actor hops and is invalidated before logout clears identity.
final class OAuthEffectPermit: @unchecked Sendable {
    private let lock = NSLock()
    private var valid = true
    var isCurrent: Bool { lock.lock(); defer { lock.unlock() }; return valid }
    func invalidate() { lock.lock(); valid = false; lock.unlock() }
}
actor AlpacaDiscordDelivery {
    private let journal: AlpacaJournal
    private let session: URLSession
    init(journal: AlpacaJournal, session: URLSession = CrierHTTPSession.shared) { self.journal = journal; self.session = session }
    func deliver(environment: AlpacaEnvironment, accountID: String, permit: OAuthEffectPermit = OAuthEffectPermit()) async throws {
        guard let webhook = StandaloneConfiguration.webhook() else { return }
        var parts = URLComponents(url: webhook, resolvingAgainstBaseURL: false)!
        parts.queryItems = [URLQueryItem(name: "wait", value: "true")]
        guard let url = parts.url else { return }
        guard let delivery = try await journal.claim(environment: environment, accountID: accountID) else { return }
        let style = UserDefaults.standard.string(forKey: "discordFillStyle") ?? "homebrew"
        let payload = UserDefaults.standard.data(forKey: "discordAlertSettings") == nil ? AlpacaAlertFormatter.payload(delivery, style: style) : DiscordAlertSettings.load().payload(delivery, style: style)
        var request = URLRequest(url: url); request.httpMethod = "POST"; request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        guard permit.isCurrent, !Task.isCancelled else { return } // Claimed journal evidence remains uncertain for manual recovery.
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { return }
        if http.statusCode == 429 {
            struct RateLimit: Decodable { let retry_after: Double }
            let seconds = (try? JSONDecoder().decode(RateLimit.self, from: data))?.retry_after ?? 60
            try await journal.rateLimited(delivery.id, retryAfter: seconds.isFinite && seconds >= 0 ? seconds : 60)
            return
        }
        if [400, 401, 403, 404].contains(http.statusCode) { try await journal.refused(delivery.id, status: http.statusCode); return }
        guard http.statusCode == 200 else { return } // Ambiguous failures remain uncertain, never automatically resent.
        struct Message: Decodable { let id: String }
        let message = try JSONDecoder().decode(Message.self, from: data)
        try await journal.delivered(delivery.id, messageID: message.id)
    }
}
