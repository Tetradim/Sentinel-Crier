import Foundation

/// Source brokerage identity is deliberately separate from IntentEvent.environment (.paper).
enum WebullHostRules {
    static func price(_ value: String) throws {
        guard try IntentExecutionPolicy.money(value) <= 100000 else { throw AlpacaError.invalid("Limit price exceeds receiver wire cap.") }
    }
    static func validate(symbol: String, asset: String, quantity: Int, price: String, stocks: [String]) throws {
        guard (1...1000).contains(quantity), ["stock", "option"].contains(asset),
              (asset == "option" ? IntentEvent.validOption(symbol) : (stocks.contains(symbol) && symbol.range(of: "^[A-Z][A-Z0-9.\\-]{0,9}$", options: .regularExpression) != nil)) else {
            throw AlpacaError.invalid("Use an exact supported stock mapping or valid OCC option symbol, and 1–1000 units.")
        }
        try self.price(price)
        if asset == "option" {
            guard let strike = Int(symbol.suffix(8)), strike > 0 else { throw AlpacaError.invalid("OCC strike must be positive.") }
        }
    }
    static func exitQuantity(requested: Int, tracked: Int, held: Int) throws -> Int {
        let value = min(requested, min(tracked, held))
        guard requested > 0, tracked >= 0, held >= 0, value > 0 else { throw AlpacaError.invalid("No verified owned source quantity available to exit.") }
        return value
    }
}
struct WebullHostReceipt: Codable {
    var client_order_id: String
    var broker_order_id: String? = nil
    var status: String
    var filled_quantity: Int
    var average_fill_price: String? = nil
}
struct WebullHostOrder: Codable, Identifiable {
    var clientID: String
    var quantity: Int
    var price: String
    var sell: Bool
    var eventID = ""
    var status = "unknown"
    var filled = 0
    var brokerID: String?
    var cancelRequested = false
    var id: String { clientID }
    var terminal: Bool { ["filled", "canceled", "rejected"].contains(status) }
    mutating func accept(_ receipt: WebullHostReceipt) throws {
        guard receipt.client_order_id == clientID,
              ["accepted", "partially_filled", "filled", "canceled", "rejected", "unknown"].contains(receipt.status),
              (filled...quantity).contains(receipt.filled_quantity),
              receipt.status != "filled" || receipt.filled_quantity == quantity,
              receipt.status != "rejected" || receipt.filled_quantity == 0,
              brokerID == nil || receipt.broker_order_id == brokerID,
              !terminal || receipt.status == status else { throw AlpacaError.invalid("Contradictory Webull receipt. Reconcile manually before continuing.") }
        if let average = receipt.average_fill_price { _ = try IntentBrokerDecimal.price(average) }
        status = receipt.status; filled = receipt.filled_quantity; brokerID = receipt.broker_order_id ?? brokerID
    }
}
struct WebullHostTrade: Codable, Identifiable {
    var id: String
    var symbol: String
    var asset: String
    var environment: String
    var account: String
    var desired: IntentEvent
    var orders: [WebullHostOrder] = []
    var rejectedOrders: [String] = []
    var settled: Bool { orders.allSatisfy(\.terminal) }
    var bought: Int { orders.filter { !$0.sell }.reduce(0) { $0 + $1.filled } }
    var owned: Int { max(0, bought - orders.filter(\.sell).reduce(0) { $0 + $1.filled }) }
}
struct WebullHostState: Codable {
    var version = 1
    var owner = ""
    var service = ""
    var authService = ""
    var pairingID = ""
    var trades: [String: WebullHostTrade] = [:]
    var outgoing: [IntentEvent] = []
    var history: [IntentEvent] = []
    mutating func enter(symbol: String, asset: String, quantity: Int, price: String, environment: String, account: String, stocks: [String]) throws -> String {
        try WebullHostRules.validate(symbol: symbol, asset: asset, quantity: quantity, price: price, stocks: stocks)
        guard ["sandbox", "production"].contains(environment), !account.isEmpty else { throw AlpacaError.invalid("Connect the selected Webull environment first.") }
        let id = UUID().uuidString.lowercased()
        let event = IntentEvent.make(trade: id, sequence: 1, action: "enter", environment: .paper, symbol: symbol, asset: asset, quantity: quantity, price: price)
        try event.validate()
        trades[id] = WebullHostTrade(id: id, symbol: symbol, asset: asset, environment: environment, account: account, desired: event)
        outgoing.append(event); history.append(event)
        return id
    }
    mutating func instruction(trade id: String, action: String, quantity: Int, price: String) throws {
        guard var trade = trades[id], ["replace", "cancel", "exit"].contains(action) else { throw AlpacaError.invalid("Unknown tracked Webull trade.") }
        let event = IntentEvent.make(trade: id, sequence: trade.desired.sequence + 1, action: action, environment: .paper, symbol: trade.symbol, asset: trade.asset, quantity: quantity, price: price)
        try WebullHostRules.price(price); try event.validate(); trade.desired = event; trades[id] = trade; outgoing.append(event); history.append(event)
    }
    mutating func prepareOrder(trade id: String, quantity: Int, price: String, sell: Bool) throws {
        guard var trade = trades[id], trade.settled, (1...1000).contains(quantity) else { throw AlpacaError.invalid("Reconcile/cancel the previous source order before another submission.") }
        trade.orders.append(WebullHostOrder(clientID: UUID().uuidString.lowercased().replacingOccurrences(of: "-", with: ""), quantity: quantity, price: price, sell: sell, eventID: trade.desired.event_id))
        trades[id] = trade
    }
    mutating func accept(trade id: String, receipt: WebullHostReceipt) throws {
        guard var trade = trades[id], let index = trade.orders.firstIndex(where: { $0.clientID == receipt.client_order_id }) else { throw AlpacaError.invalid("Unknown source receipt.") }
        try trade.orders[index].accept(receipt)
        let reject = !trade.orders[index].sell && receipt.status == "rejected" && !trade.rejectedOrders.contains(receipt.client_order_id)
        if reject { trade.rejectedOrders.append(receipt.client_order_id) }
        trades[id] = trade
        if reject { try instruction(trade: id, action: "cancel", quantity: trade.desired.quantity, price: trade.desired.limit_price) }
    }
    func validate() throws {
        guard version == 1 else { throw AlpacaError.invalid("Unsupported Webull journal; retain it for recovery.") }
        guard Set(history.map(\.event_id)).count == history.count, outgoing.allSatisfy({ history.contains($0) }) else { throw AlpacaError.invalid("Webull instruction history is inconsistent.") }
        for event in history { try WebullHostRules.price(event.limit_price); try event.validate(); guard event.environment == .paper else { throw AlpacaError.invalid("Webull receiver must remain PAPER.") } }
        for (id, trade) in trades {
            try trade.desired.validate()
            let events = history.filter { $0.trade_id == id }
            guard !events.isEmpty, events.last == trade.desired, events.map(\.sequence) == Array(1...events.count) else { throw AlpacaError.invalid("Webull instruction sequence has a gap.") }
            guard id == trade.id, trade.desired.trade_id == id, trade.desired.environment == .paper,
                  ["sandbox", "production"].contains(trade.environment), !trade.account.isEmpty,
                  trade.orders.allSatisfy({ order in (1...1000).contains(order.quantity) && (0...order.quantity).contains(order.filled) && ["accepted", "partially_filled", "filled", "canceled", "rejected", "unknown"].contains(order.status) && history.contains(where: { event in event.event_id == order.eventID && event.trade_id == id }) }) else { throw AlpacaError.invalid("Webull journal identity is inconsistent.") }
        }
    }
}
