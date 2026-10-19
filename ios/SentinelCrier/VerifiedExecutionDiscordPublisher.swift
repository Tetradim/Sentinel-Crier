import Foundation

/// Sends only entries previously recorded from authoritative broker executions.
/// The outbox marks a message uncertain before POST; ambiguous outcomes are
/// intentionally never resent automatically.
actor VerifiedExecutionDiscordPublisher {
    private let outbox: VerifiedExecutionOutbox
    init(outbox: VerifiedExecutionOutbox) { self.outbox = outbox }

    func deliverNext() async throws {
        guard let webhook = StandaloneConfiguration.webhook(),
              let entry = try await outbox.claimForDelivery() else { return }

        let e = entry.execution
        let contract = e.contract
        let content = """
        ✅ BROKER-CONFIRMED EXECUTION
        Broker: \(e.brokerId)
        Contract: \(contract.underlying) \(contract.expiration) \(contract.strike)\(contract.right)
        Action: \(e.action.rawValue)
        Filled: \(e.incrementalQuantity) @ $\(e.executionPrice)
        Execution ID: \(e.executionId)
        """
        guard var parts = URLComponents(url: webhook, resolvingAgainstBaseURL: false) else { return }
        parts.queryItems = [URLQueryItem(name: "wait", value: "true")]
        guard let url = parts.url else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 12
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "content": content,
            "allowed_mentions": ["parse": []]
        ])
        let (data, response) = try await CrierHTTPSession.shared.data(for: request)
        if let http = response as? HTTPURLResponse, http.statusCode == 429 {
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            try await outbox.rateLimited(id: entry.id, seconds: object?["retry_after"] as? Double ?? 60)
            return
        }
        guard let http = response as? HTTPURLResponse, http.statusCode == 200,
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let id = object["id"] as? String, !id.isEmpty,
              id.allSatisfy({ $0.isNumber }) else { return }
        try await outbox.confirmDelivery(id: entry.id, discordMessageId: id)
    }
}
