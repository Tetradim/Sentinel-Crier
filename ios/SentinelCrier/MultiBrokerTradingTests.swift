import XCTest
@testable import SentinelCrier

final class MultiBrokerTradingTests: XCTestCase {
    private func account(_ broker: String) -> LiveAccount {
        LiveAccount(brokerId: broker, accountId: "primary",
                    displayName: broker, currency: "USD",
                    buyingPower: 1_000, equity: 2_000)
    }

    func testPerBrokerQuantity() throws {
        let allocations = try MultiBrokerAllocator.allocate(
            quantity: 10, mode: .perBroker,
            accounts: [account("webull"), account("alpaca")])
        XCTAssertEqual(allocations.map(\.contracts), [10, 10])
        XCTAssertEqual(MultiBrokerAllocator.totalContracts(allocations), 20)
    }

    func testSplitQuantityWithRemainder() throws {
        let allocations = try MultiBrokerAllocator.allocate(
            quantity: 11, mode: .splitTotal,
            accounts: [account("webull"), account("alpaca")])
        XCTAssertEqual(allocations.map(\.contracts), [6, 5])
        XCTAssertEqual(MultiBrokerAllocator.totalContracts(allocations), 11)
    }

    func testSplitRejectsTooFewContracts() {
        XCTAssertThrowsError(try MultiBrokerAllocator.allocate(
            quantity: 1, mode: .splitTotal,
            accounts: [account("webull"), account("alpaca")]))
    }

    func testRejectsDuplicateAccountSelection() {
        XCTAssertThrowsError(try MultiBrokerAllocator.allocate(
            quantity: 10, mode: .perBroker,
            accounts: [account("webull"), account("webull")]))
    }

    func testCombinedBalancesDoNotAssumeMissingAccountIsZero() {
        let missing = LiveAccount(brokerId: "alpaca", accountId: "primary",
                                  displayName: "alpaca", currency: "USD",
                                  buyingPower: nil, equity: nil)
        let snapshot = BrokerAccountSnapshot(
            capturedAt: Date(), accounts: [account("webull"), missing],
            positions: [])
        XCTAssertNil(snapshot.totalEquity(currency: "USD"))
        XCTAssertNil(snapshot.totalBuyingPower(currency: "USD"))
    }

    func testCombinedBalancesIgnoreOtherCurrency() {
        let snapshot = BrokerAccountSnapshot(
            capturedAt: Date(), accounts: [account("webull")], positions: [])
        XCTAssertEqual(snapshot.totalEquity(currency: "USD"), 2_000)
        XCTAssertNil(snapshot.totalEquity(currency: "CAD"))
    }

    func testOptionalAutomationPreferencesAreDisabledByDefault() {
        // New-install defaults are false. No optional automation is backed by
        // a broker endpoint or enabled by this view.
        XCTAssertFalse(UserDefaults.standard.bool(
            forKey: TradingPreferences.autoStopsKey))
        XCTAssertFalse(UserDefaults.standard.bool(
            forKey: TradingPreferences.autoTakeProfitKey))
        XCTAssertFalse(UserDefaults.standard.bool(
            forKey: TradingPreferences.automatedDiscordTradingKey))
    }
}
