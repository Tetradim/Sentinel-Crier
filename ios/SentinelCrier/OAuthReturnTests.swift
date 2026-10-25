import XCTest
@testable import SentinelCrier

// XCTest keeps these tests compatible with the project's Swift 5.9 toolchain.
final class OAuthReturnTests: XCTestCase {
    private struct Fixture: Decodable {
        struct Vector: Decodable { let name: String; let uri: String; let valid: Bool }
        let flow: String
        let canonical: String
        let cases: [Vector]
    }
    private func fixture() throws -> Fixture {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "oauth-return", withExtension: "json"))
        return try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url))
    }
    private func context(owner: String = "owner-1", provider: String = "alpaca",
                         environment: String = "paper", purpose: String = "alerts") throws -> OAuthReturnContext {
        try XCTUnwrap(OAuthReturnContext(owner: owner, provider: provider, environment: environment, purpose: purpose))
    }
    func testSharedCanonicalContract() throws {
        let f = try fixture()
        for c in f.cases { XCTAssertEqual(OAuthReturn.parse(c.uri), c.valid ? f.flow : nil, c.name) }
    }
    func testOpaqueOwnerEqualityUsesExactUTF8() throws {
        let f = try fixture()
        let original = try context(owner: "caf\u{00e9}")
        let different = try context(owner: "cafe\u{0301}")
        XCTAssertNotEqual(original, different)
        let pending = try XCTUnwrap(PendingOAuthReturn(flow: f.flow, context: original, expiresAt: 100))
        XCTAssertNil(pending.matchReturn(f.canonical, expectedFlow: f.flow, expectedContext: different, now: 1))
        XCTAssertEqual(pending.matchReturn(f.canonical, expectedFlow: f.flow, expectedContext: original, now: 1), original)
    }
    func testOnlyTrustedContextCanMatchOnce() throws {
        let f = try fixture(); let c = try context()
        let p = try XCTUnwrap(PendingOAuthReturn(flow: f.flow, context: c, expiresAt: 100))
        let wrongContexts = [try context(owner: "owner-2"), try context(provider: "discord"),
                             try context(environment: "live"), try context(purpose: "trade")]
        for wrong in wrongContexts {
            XCTAssertNil(p.matchReturn(f.canonical, expectedFlow: f.flow, expectedContext: wrong, now: 1))
        }
        let other = String(repeating: "B", count: 43)
        XCTAssertNil(p.matchReturn(f.canonical, expectedFlow: other, expectedContext: c, now: 1))
        XCTAssertNil(p.matchReturn(f.canonical.replacingOccurrences(of: f.flow, with: other), expectedFlow: f.flow, expectedContext: c, now: 1))
        XCTAssertNil(p.matchReturn(f.canonical + "&code=secret", expectedFlow: f.flow, expectedContext: c, now: 1))
        XCTAssertEqual(p.matchReturn(f.canonical, expectedFlow: f.flow, expectedContext: c, now: 99), c)
        XCTAssertNil(p.matchReturn(f.canonical, expectedFlow: f.flow, expectedContext: c, now: 99))
    }
    func testCancellationExpirationInvalidationAndRestartRejectReturns() throws {
        let f = try fixture(); let c = try context()
        for action in ["cancel", "invalidate", "timeout", "nonfinite"] {
            let p = try XCTUnwrap(PendingOAuthReturn(flow: f.flow, context: c, expiresAt: 100))
            switch action {
            case "cancel": p.cancel()
            case "invalidate": p.invalidate()
            case "timeout": XCTAssertNil(p.matchReturn(f.canonical, expectedFlow: f.flow, expectedContext: c, now: 100))
            default: XCTAssertNil(p.matchReturn(f.canonical, expectedFlow: f.flow, expectedContext: c, now: .nan))
            }
            XCTAssertNil(p.matchReturn(f.canonical, expectedFlow: f.flow, expectedContext: c, now: 1), action)
        }
        XCTAssertNil(OAuthReturn.matchPending(nil, uri: f.canonical, expectedFlow: f.flow, expectedContext: c, now: 1))
        XCTAssertNil(PendingOAuthReturn(flow: "short", context: c, expiresAt: 100))
        XCTAssertNil(PendingOAuthReturn(flow: f.flow, context: c, expiresAt: .infinity))
        XCTAssertNil(OAuthReturnContext(owner: "owner", provider: "discord", environment: "live", purpose: "trade"))
    }
}
