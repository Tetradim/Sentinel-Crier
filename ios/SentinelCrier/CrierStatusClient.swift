import Foundation

/// Read-only authenticated status client for the existing Crier backend.
/// Credentials must be held only in memory until Keychain integration is added.
struct CrierStatusClient {
    let baseURL: URL
    let accessToken: String

    enum ClientError: Error {
        case invalidURL
        case unauthorized
        case invalidResponse
    }

    func status() async throws -> Status {
        guard baseURL.scheme?.lowercased() == "https",
              baseURL.host != nil,
              baseURL.user == nil,
              baseURL.password == nil,
              !accessToken.isEmpty else { throw ClientError.invalidURL }
        var request = URLRequest(url: baseURL.appendingPathComponent("api/status"))
        request.setValue("Bearer " + accessToken, forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 10
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw ClientError.invalidResponse }
        if response.statusCode == 401 { throw ClientError.unauthorized }
        guard response.statusCode == 200 else { throw ClientError.invalidResponse }
        return try JSONDecoder().decode(Status.self, from: data)
    }

    struct Status: Decodable {
        let mode: String
        let delivery_enabled: Bool
        let discord_configured: Bool
        let paused: Bool
    }
}
