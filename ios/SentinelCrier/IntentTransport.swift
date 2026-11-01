import Foundation

/// Relay I/O has no access to trading state or broker credentials. Session
/// generation and authentication revocation remain at the controller boundary.
struct IntentTransport {
    let session: URLSession
    func request(pair: IntentPairing, query: String = "", body: Data? = nil, resource: String = "events") async throws -> (Data, HTTPURLResponse) {
        guard let url = URL(string: pair.url.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/api/sync/" + resource + query) else { throw AlpacaError.invalid("Invalid relay URL.") }
        var request = URLRequest(url: url)
        request.httpMethod = body == nil ? "GET" : "POST"; request.httpBody = body; request.timeoutInterval = 30
        request.setValue("Bearer " + pair.token, forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw AlpacaError.invalid("Relay returned an invalid response.") }
        return (data, http)
    }
}
