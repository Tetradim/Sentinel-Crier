import Foundation

/// Deliberately separate from crier.fill.v1: OCR is not an authenticated broker fill.
struct ScreenEvidence: Codable {
    let schema: String
    let source: String
    let broker: String
    let symbol: String
    let expiration: String
    let right: String
    let strike: String
    let side: String
    let quantity: Int
    let fillPrice: String
    let observedAt: String
    let evidenceId: String

    init(candidate: ScreenTradeCandidate, evidenceId: UUID = UUID()) {
        self.schema = "crier.screen-observation.v1"
        self.source = "ios-replaykit-vision"
        self.broker = candidate.broker
        self.symbol = candidate.symbol
        self.expiration = candidate.expiration
        self.right = candidate.right
        self.strike = NSDecimalNumber(decimal: candidate.strike).stringValue
        self.side = candidate.side
        self.quantity = candidate.quantity
        self.fillPrice = NSDecimalNumber(decimal: candidate.price).stringValue
        self.observedAt = ISO8601DateFormatter().string(from: candidate.observedAt)
        self.evidenceId = evidenceId.uuidString
    }
}

/// No networking occurs unless the user explicitly configures an HTTPS endpoint
/// and a short-lived upload token. Endpoint must validate auth and treat evidence
/// as pending review, NEVER as a broker-verified fill.
struct ScreenEvidenceTransport {
    let endpoint: URL
    let bearerToken: String

    func submit(_ evidence: ScreenEvidence) async throws {
        guard endpoint.scheme?.lowercased() == "https",
              endpoint.user == nil, endpoint.password == nil,
              !bearerToken.isEmpty else { throw TransportError.invalidConfiguration }
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(bearerToken)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 10
        request.httpBody = try JSONEncoder().encode(evidence)
        let (_, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw TransportError.serverRejected
        }
    }

    enum TransportError: Error { case invalidConfiguration, serverRejected }
}
