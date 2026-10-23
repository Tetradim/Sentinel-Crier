import Foundation

enum QuickConnection {
    struct Invitation { let url: URL; let code: String }
    private struct Credential: Decodable { let token: String; let role: String; let environment: AlpacaEnvironment }
    private struct Invite: Decodable { let code: String }
    static var defaultService: String {
        guard let file = Bundle.main.url(forResource: "connection-service", withExtension: "json"),
              let data = try? Data(contentsOf: file),
              let value = try? JSONDecoder().decode([String: String].self, from: data) else { return "" }
        return value["url"] ?? ""
    }
    static func origin(_ text: String) throws -> URL {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { throw AlpacaError.invalid("Set up a hosted connection service and enter its HTTPS URL in Advanced, or paste a receiver invitation link.") }
        guard var parts = URLComponents(string: value), parts.scheme == "https", let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              ["", "/"].contains(parts.path), parts.port == nil || (1...65535).contains(parts.port!) else {
            throw AlpacaError.invalid("Connection service must be an HTTPS origin without credentials, path, query or fragment.")
        }
        parts.path = ""
        guard let url = parts.url else { throw AlpacaError.invalid("Invalid connection service URL.") }
        return url
    }
    static func code(_ text: String) throws -> String {
        let value = text.uppercased().filter { !$0.isWhitespace && $0 != "-" }
        guard value.count == 16, value.allSatisfy({ "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567".contains($0) }) else {
            throw AlpacaError.invalid("Enter the 16-character invitation code or complete invitation link.")
        }
        return value
    }
    static func invitation(_ text: String, service: String) throws -> Invitation {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.contains("://") {
            guard var parts = URLComponents(string: value), parts.path == "/connect", parts.query == nil, let fragment = parts.fragment else {
                throw AlpacaError.invalid("Invalid invitation link.")
            }
            parts.path = ""; parts.fragment = nil
            return Invitation(url: try origin(parts.string ?? ""), code: try code(fragment))
        }
        return Invitation(url: try origin(service), code: try code(value))
    }
    private static func post<T: Decodable>(_ type: T.Type, origin: URL, path: String, body: [String: String]? = nil, token: String? = nil) async throws -> T {
        var request = URLRequest(url: origin.appendingPathComponent("api/connect/" + path))
        request.httpMethod = "POST"; request.timeoutInterval = 30
        if let body { request.httpBody = try JSONEncoder().encode(body) }
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        do {
            let (data, response) = try await CrierHTTPSession.shared.data(for: request)
            guard let response = response as? HTTPURLResponse else { throw AlpacaError.invalid("Connection service returned an invalid response.") }
            guard (200..<300).contains(response.statusCode) else { throw AlpacaError.invalid("Connection service refused the request (HTTP \(response.statusCode)). An invitation may be expired or already used; request a new one.") }
            return try JSONDecoder().decode(type, from: data)
        } catch let error as AlpacaError { throw error }
        catch { throw AlpacaError.invalid("Could not reach or read the connection service. Check the service URL and try again.") }
    }
    private static func pairing(_ credential: Credential, url: URL, role: String, environment: AlpacaEnvironment) throws -> IntentPairing {
        guard credential.role == role, credential.environment == environment else { throw AlpacaError.invalid("Invitation role or environment differs from this device. Select the matching environment before pairing.") }
        let pair = IntentPairing(url: url, token: credential.token, environment: credential.environment, role: credential.role)
        return try IntentPairing.decode(String(decoding: JSONEncoder().encode(pair), as: UTF8.self))
    }
    static func host(service: String, environment: AlpacaEnvironment) async throws -> IntentPairing {
        let url = try origin(service)
        let value = try await post(Credential.self, origin: url, path: "host", body: ["name": "iPhone", "environment": environment.rawValue])
        return try pairing(value, url: url, role: "host", environment: environment)
    }
    static func receive(_ invitation: Invitation, environment: AlpacaEnvironment) async throws -> IntentPairing {
        let value = try await post(Credential.self, origin: invitation.url, path: "receive", body: ["code": invitation.code, "environment": environment.rawValue])
        return try pairing(value, url: invitation.url, role: "follower", environment: environment)
    }
    static func invite(_ pair: IntentPairing) async throws -> String {
        let url = try origin(pair.url.absoluteString)
        let value = try await post(Invite.self, origin: url, path: "invite", token: pair.token)
        return url.absoluteString + "/connect#" + (try code(value.code))
    }
    struct Receiver: Decodable, Identifiable { let id: String; let created: Double; let revoked: Int }
    static func receivers(_ pair: IntentPairing, session: URLSession = CrierHTTPSession.shared) async throws -> [Receiver] {
        guard pair.role == "host" else { throw AlpacaError.invalid("Host credentials required.") }
        var request = URLRequest(url: try origin(pair.url.absoluteString).appendingPathComponent("api/connect/receivers"))
        request.timeoutInterval = 30
        request.setValue("Bearer " + pair.token, forHTTPHeaderField: "Authorization")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw AlpacaError.invalid("Invalid receiver response.") }
        guard (200..<300).contains(http.statusCode) else { throw AlpacaError.http(http.statusCode) }
        return try JSONDecoder().decode([Receiver].self, from: data)
    }
    static func revoke(_ receiver: Receiver, pairing: IntentPairing, session: URLSession = CrierHTTPSession.shared) async throws {
        guard pairing.role == "host", UUID(uuidString: receiver.id) != nil else { throw AlpacaError.invalid("Invalid receiver identity.") }
        var request = URLRequest(url: try origin(pairing.url.absoluteString).appendingPathComponent("api/connect/receivers/" + receiver.id + "/revoke"))
        request.httpMethod = "POST"; request.timeoutInterval = 30
        request.setValue("Bearer " + pairing.token, forHTTPHeaderField: "Authorization")
        let (_, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw AlpacaError.invalid("Invalid revocation response.") }
        guard (200..<300).contains(http.statusCode) else { throw AlpacaError.http(http.statusCode) }
    }

}
