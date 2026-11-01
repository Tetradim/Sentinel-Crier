import Foundation

/// Observational projection has no controller, transport or execution capability.
struct IntentTelemetry {
    let accountID: String
    let hosting: Bool
    let paused: Bool
    let binding: IntentPolicyBinding?
    let brokerObserved: String?
    let quote: DiagnosticQuote?
    private func terminal(_ order: AlpacaOrder) -> Bool { ["filled", "canceled", "expired", "rejected", "replaced"].contains(order.status) }
    func report(_ trade: IntentTrade, event: IntentEvent) -> CopyStatus {
        func premium(sell: Bool) -> String? {
            do {
                var total = Decimal(0)
                for mutation in trade.mutations where mutation.sell == sell {
                    guard let order = mutation.order else { continue }
                    try mutation.validate(order, symbol: event.symbol)
                    guard let filled = Decimal(string: order.filled_qty) else { return nil }
                    if filled > 0 {
                        guard let average = CopyMoney.decimal(order.filled_avg_price), average > 0 else { return nil }
                        total = try IntentBrokerDecimal.add(total, IntentBrokerDecimal.multiply(filled, average))
                    }
                }
                return NSDecimalNumber(decimal: total).stringValue
            } catch { return nil }
        }
        let binding = trade.policyBinding ?? self.binding
        let verified = binding.map { $0.accountID == accountID && $0.environment == event.environment && $0.symbol == event.symbol && $0.asset == event.asset && $0.currency == "USD" && $0.multiplier == (event.asset == "option" ? 100 : 1) } == true
        var status = "received"; var reason: String?
        if trade.mutations.contains(where: { $0.notSubmitted != true && ($0.order == nil || $0.cancelUnknown) }) { status = "unknown"; reason = "reconciliation_required" }
        else if trade.mutations.contains(where: { $0.order?.status == "pending_cancel" }) { status = "cancel_pending" }
        else if trade.bought > 0 && trade.bought == trade.totalSold { status = "closed" }
        else if trade.mutations.contains(where: { $0.order.map { !terminal($0) } ?? false }) { status = trade.bought > 0 ? "partially_filled" : "working" }
        else if trade.bought > 0 { status = "filled" }
        else if trade.mutations.contains(where: { $0.notSubmitted == true }) { status = "not_submitted"; reason = "not_submitted" }
        else if trade.invalidated { status = "canceled" }
        else if trade.entrySkipped == true || (!hosting && paused) { status = "blocked"; reason = "entries_paused" }
        else if trade.completed == event.event_id { status = "not_submitted"; reason = "not_submitted" }
        return CopyStatus(event_id: event.event_id, revision: 1, observed_at: "", broker_observed_at: brokerObserved, state: status,
                          target_quantity: trade.entryPlans?[event.event_id]?.target ?? (hosting || trade.policySnapshot?.policy == nil ? event.quantity : nil),
                          bought: trade.bought, sold: trade.totalSold, buy_premium: premium(sell: false), sell_premium: premium(sell: true),
                          currency: verified ? "USD" : nil, multiplier: verified ? binding?.multiplier : nil, fees: nil, quote: quote, reason: reason)
    }
}
