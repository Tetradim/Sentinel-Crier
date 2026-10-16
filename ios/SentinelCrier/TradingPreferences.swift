import Foundation

/// Lightweight local UI preferences. They never authorize an order.
enum TradingPreferences {
    static let quantityModeKey = "trading.quantityMode"
    static let contractQuantityKey = "trading.contractQuantity"
    static let hideBalancesKey = "trading.hideBalances"
    static let defaultOrderTypeKey = "trading.defaultOrderType"
    static let advancedChartToolsKey = "trading.advancedChartTools"

    /// Optional behavior must be opt-in; no automatic live actions are enabled.
    static let autoStopsKey = "trading.autoStopsEnabled"
    static let autoTakeProfitKey = "trading.autoTakeProfitEnabled"
    static let automatedDiscordTradingKey = "trading.automatedDiscordTradingEnabled"

    static func mode(rawValue: String) -> MultiBrokerQuantityMode {
        MultiBrokerQuantityMode(rawValue: rawValue) ?? .perBroker
    }
}

struct BrokerAccountSnapshot: Codable {
    let capturedAt: Date
    let accounts: [LiveAccount]
    let positions: [LivePosition]

    /// Missing values stay unknown rather than silently becoming zero.
    func totalEquity(currency: String) -> Decimal? {
        let relevant = accounts.filter { $0.currency == currency }
        guard !relevant.isEmpty, relevant.allSatisfy({ $0.equity != nil }) else { return nil }
        return relevant.reduce(Decimal.zero) { $0 + ($1.equity ?? .zero) }
    }

    func totalBuyingPower(currency: String) -> Decimal? {
        let relevant = accounts.filter { $0.currency == currency }
        guard !relevant.isEmpty, relevant.allSatisfy({ $0.buyingPower != nil }) else { return nil }
        return relevant.reduce(Decimal.zero) { $0 + ($1.buyingPower ?? .zero) }
    }
}
