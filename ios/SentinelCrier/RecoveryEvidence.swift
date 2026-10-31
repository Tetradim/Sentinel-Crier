import Foundation

struct RecoveryOrderEvidence: Identifiable {
    var id: String { ticket.id }
    let ticket: AlpacaTicket
    let order: AlpacaOrder?

    static func validate(_ order: AlpacaOrder, ticket: AlpacaTicket) throws {
        guard let filled = Decimal(string: order.filled_qty), !filled.isNaN else {
            throw AlpacaError.invalid("Broker filled quantity is invalid; preserve the original journal.")
        }
        var quantity = filled
        var integral = Decimal()
        NSDecimalRound(&integral, &quantity, 0, .plain)
        guard order.client_order_id == ticket.id, !order.id.isEmpty,
              order.symbol == ticket.symbol, order.side == ticket.side,
              order.qty.flatMap({ Decimal(string: $0) }) == Decimal(ticket.quantity),
              order.limit_price.flatMap({ Decimal(string: $0) }) == ticket.limitPrice,
              filled >= 0, filled <= Decimal(ticket.quantity),
              integral == filled else {
            throw AlpacaError.invalid("Broker evidence differs from the saved order. Preserve the original journal.")
        }
    }
}

struct RecoveryBrokerSnapshot {
    let accountID: String
    let environment: AlpacaEnvironment
    let checkedAt: Date
    let orders: [RecoveryOrderEvidence]
    let positions: [AlpacaPosition]
}
