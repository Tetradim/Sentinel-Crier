import XCTest
@testable import SentinelCrier
final class QuickConnectionTests: XCTestCase {
    func testOriginRejectsUnsafeComponents() throws {
        for value in ["", "http://relay.example", "https://user@relay.example", "https://relay.example/api", "https://relay.example?q=x", "https://relay.example#secret"] {
            XCTAssertThrowsError(try QuickConnection.origin(value))
        }
        XCTAssertEqual(try QuickConnection.origin(" https://relay.example/ ").absoluteString, "https://relay.example")
    }
    func testShareLinkSuppliesOrigin() throws {
        let invite = try QuickConnection.invitation("https://relay.example/connect#ABCD2345EFGH2345", service: "")
        XCTAssertEqual(invite.url.absoluteString, "https://relay.example")
        XCTAssertEqual(invite.code, "ABCD2345EFGH2345")
    }
    func testSupabaseGatewayPreservesBaseAndEndpointPaths() throws {
        let base = "https://project.supabase.co/functions/v1/crier"
        let url = try QuickConnection.origin(base + "/")
        XCTAssertEqual(url.absoluteString, base)
        let invite = try QuickConnection.invitation(base + "/connect#ABCD2345EFGH2345", service: "")
        XCTAssertEqual(invite.url, url)
        XCTAssertEqual(url.appendingPathComponent("api/sync/events").path, "/functions/v1/crier/api/sync/events")
        for suffix in ["/other", "?", "#", "/../other", "//", "/%63onnect"] {
            XCTAssertThrowsError(try QuickConnection.origin(base + suffix))
        }
        XCTAssertThrowsError(try QuickConnection.invitation(base + "/other/connect#ABCD2345EFGH2345", service: ""))
    }
    func testCodeNormalizationAndValidation() throws {
        XCTAssertEqual(try QuickConnection.code("abcd-2345 efgh-2345"), "ABCD2345EFGH2345")
        for value in ["ABCD2345EFGH6782", "ABC", "ABCD2345EFGH2340"] { XCTAssertThrowsError(try QuickConnection.code(value)) }
    }
    func testShareLinkRejectsQueryAndUnexpectedPath() {
        for value in ["https://relay.example/connect?token=x#ABCD2345EFGH2345", "https://relay.example/other#ABCD2345EFGH2345", "http://relay.example/connect#ABCD2345EFGH2345"] {
            XCTAssertThrowsError(try QuickConnection.invitation(value, service: "https://other.example"))
        }
    }
}

